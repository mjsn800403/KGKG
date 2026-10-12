# htmlparser_logical.py
#
# Breadcrumb-driven, link-crawled parser with automated zip processing.
# 
# USAGE:
#   python htmlparser_logical.py "path/to/backend_folder"
#
# This will:
#   1. Extract all KGTV *.zip files in the current directory (parallel)
#   2. Parse each extracted HTML folder into a database (parallel)
#   3. Copy databases to Database_warehouse/ (renamed without prefix/year)
#   4. Copy images folders to static_warehouse/ (renamed to match)
#   5. Update backend db.sqlite3 with car information

import re
import json
import sqlite3
import hashlib
import argparse
import sys
import os
import shutil
import zipfile
from collections import deque
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from bs4 import BeautifulSoup

PARSER = "html5lib"  # MANDATORY: html.parser / lxml mis-nest the unclosed <li> tags.

# How often (in pages) the resumable crawl flushes its visited/queue snapshot.
# On an interruption, at most this many pages of frontier progress are redone.
CHECKPOINT_EVERY = 250

# Root-level subtrees pruned at crawl time. "Repair and Diagnosis (Single Page)"
# is the site's all-in-one aggregate of the normal Repair and Diagnosis tree — a
# strict duplicate (verified: 0 content blobs unique to it). Excluding it here
# keeps every freshly ingested car free of the redundant branch, instead of
# deleting it from the warehouse + RAG after the fact. Match is on the page's
# parsed title (h1/breadcrumb), so the whole subtree under it is pruned.
EXCLUDED_PAGE_TITLES = {"Repair and Diagnosis (Single Page)"}

# Thread-safe print lock
print_lock = threading.Lock()

# Serializes all writes to the backend zip-level ledger across worker threads.
ledger_lock = threading.Lock()


class _StubSkip(Exception):
    """Internal: a breadcrumb-less stub page with no recovery anchor."""


class CrawlPaused(Exception):
    """Raised by a crawl when an external cancel_event is set. Not an error: the
    frontier has just been checkpointed, so the next run resumes from this point.
    Callers must treat this as 'paused', NOT 'failed'."""


class LogicalHTMLParser:
    def __init__(self, html_dir: str, index_file: str, db_path: str = "nodes.db"):
        # html_dir is searched ONLY to locate files by basename (layout-agnostic).
        self.html_dir = Path(html_dir).resolve()
        self.index_file = Path(index_file).resolve()
        self.db_path = db_path
        self.files_by_basename: Dict[str, Path] = {}
        self.model_root: str = ""        # escaped last-breadcrumb segment of index.html
        # basename -> (abs_path, parent_path) memoized breadcrumb peek, so checking
        # "is this link a first-degree child" never re-parses the same target twice.
        self._breadcrumb_cache: Dict[str, Optional[Tuple[str, Optional[str]]]] = {}
        self._index_files()
        self.setup_database()

    # ------------------------------------------------------------------ setup
    def _index_files(self) -> None:
        """Map EVERY *.html basename -> its path. Folder structure is ignored as
        a signal; this index exists purely so a link like '../pages/41928.html'
        can be resolved to bytes on disk no matter where the file actually sits."""
        for p in self.html_dir.rglob("*.html"):
            if p.name.startswith("."):
                continue
            key = p.name.lower()
            if key not in self.files_by_basename:
                self.files_by_basename[key] = p
            elif self.files_by_basename[key] != p:
                with print_lock:
                    print(f"⚠️ duplicate basename '{p.name}' — keeping "
                          f"{self.files_by_basename[key]}, ignoring {p}")
        with print_lock:
            print(f"🔎 Indexed {len(self.files_by_basename)} html files (by basename)")

    def setup_database(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id          TEXT PRIMARY KEY,           -- sha1(path)
                parent_id   TEXT,                       -- sha1(parent_path); NULL at root
                path        TEXT NOT NULL,              -- absolute breadcrumb logical path
                title       TEXT NOT NULL,
                node_type   TEXT,                       -- DOM role: 'root'|'folder'|'leaf' (NULL on page-base until merged)
                file_type   TEXT,                       -- 'root_path' | 'intermediate_path' | 'end_path' (NULL for page-less DOM folders)
                href        TEXT,                       -- original link target, if any
                source_file TEXT,                       -- absolute path of the html this row was parsed from
                sort_order  INTEGER NOT NULL DEFAULT 0,
                depth       INTEGER NOT NULL DEFAULT 0,
                root_order  INTEGER,                    -- ordering among root nodes (NULL otherwise)
                content     TEXT,                       -- raw div.main inner HTML for end_path rows
                updated_at  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id, sort_order);
            CREATE INDEX IF NOT EXISTS idx_nodes_path   ON nodes(path);
            CREATE INDEX IF NOT EXISTS idx_nodes_root   ON nodes(root_order);

            -- Resumable-crawl checkpoint. One row per key; holds a JSON snapshot of
            -- the BFS 'visited' set, the pending 'queue' frontier, and progress
            -- counters, rewritten atomically every CHECKPOINT_EVERY pages. If the
            -- run is killed, the next run reloads this and continues mid-crawl.
            CREATE TABLE IF NOT EXISTS crawl_state (
                k  TEXT PRIMARY KEY,   -- 'snapshot' | 'status'
                v  TEXT                -- JSON blob
            );
        """)
        conn.commit()
        conn.close()
        with print_lock:
            print(f"✅ Database initialized: {self.db_path}")

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _hash(path: str) -> str:
        return hashlib.sha1(path.encode("utf-8")).hexdigest()

    # A literal '/' that is PART OF A NAME (e.g. "Collision/Avoidance",
    # "Different variant/trim", "A/C") must never collide with the hierarchy
    # separator. We swap it for U+2044 internally and only swap back for display.
    _SLASH_ESCAPE = "\u2044"  # FRACTION SLASH — never appears in the source HTML.

    @classmethod
    def _escape_text(cls, text: str) -> str:
        """Escape a single ALREADY-DECODED segment (breadcrumb text / link text)."""
        return text.replace("/", cls._SLASH_ESCAPE)

    @classmethod
    def _decode_frag(cls, frag: str) -> str:
        """Decode a percent-encoded <a name>/href FRAGMENT path into an escaped
        relative logical path. Split on '/' FIRST (real separators), then unquote
        each segment, then escape any literal '/' that was encoded as %2F inside a
        segment — so e.g. 'Accessories%20%26%20Equipment/Collision%2FAvoidance/'
        -> 'Accessories & Equipment' / 'Collision⁄Avoidance'."""
        out = []
        for seg in frag.split("/"):
            if seg == "":
                continue
            out.append(unquote(seg).replace("/", cls._SLASH_ESCAPE))
        return "/".join(out)

    @classmethod
    def _unescape(cls, text: str) -> str:
        """Reverse escaping, for human-facing display only."""
        return text.replace(cls._SLASH_ESCAPE, "/")

    @staticmethod
    def _norm(path: str) -> str:
        """Collapse duplicate slashes and strip edge slashes. Logical paths never
        contain 'index.html' so no special-casing is needed."""
        p = re.sub(r"/+", "/", path).strip("/")
        return "" if p == "." else p

    @classmethod
    def _parent_path(cls, path: str) -> Optional[str]:
        """Parent in the canonical tree. '' is the (single) true root and has no
        parent (-> None). A single-segment path's parent is '' only if it is the
        model root; here the model root IS a single segment, so its parent is None."""
        if path == "":
            return None
        if "/" not in path:
            return None  # the model root (a single segment) has no parent
        return path.rsplit("/", 1)[0]

    # ------------------------------------------------------------- breadcrumb
    def _breadcrumb_segments(self, soup: BeautifulSoup) -> List[str]:
        """Ordered, escaped text of every <a class='breadcrumb-part'>."""
        # find_all (not CSS .select) so we don't depend on the soupsieve package,
        # whose version varies across machines (e.g. macOS lacked .select support).
        return [self._escape_text(a.get_text(strip=True))
                for a in soup.find_all("a", class_="breadcrumb-part")]

    def _page_abs_path(self, segs: List[str]) -> str:
        """Absolute logical path of a page = its breadcrumb from the MODEL ROOT
        onward (dropping the dead 'Home > Toyota > 2025' prefix that points at
        404.html). The model root is the last breadcrumb segment of index.html."""
        if self.model_root and self.model_root in segs:
            # last occurrence, in case a name repeats upstream
            i = len(segs) - 1 - segs[::-1].index(self.model_root)
            segs = segs[i:]
        return self._norm("/".join(segs))

    # --------------------------------------------------------------- linkres
    def _resolve_basename(self, href: Optional[str]) -> Optional[str]:
        """Followable page basename for an href, else None. Fragments are stripped;
        404.html / about.html / externals / pure-anchors are rejected."""
        if not href:
            return None
        path_part = urlsplit(href).path  # drops #fragment and ?query
        base = Path(path_part).name.lower()
        if not base or base in ("404.html", "about.html"):
            return None
        if not base.endswith((".html", ".htm")):
            return None
        return base

    @staticmethod
    def _has_fragment(href: Optional[str]) -> bool:
        return bool(href) and "#" in href

    def _is_followable(self, base: Optional[str]) -> bool:
        return base is not None and base in self.files_by_basename

    # ------------------------------------------------------------- classify
    def _nav_ul(self, main):
        """The split-tree navigation <ul> is the one that is a DIRECT child of
        div.main. Content lists (e.g. <ul class='BULLET'> inside an article) are
        nested deeper and are intentionally never treated as navigation. (Still
        used to build structural rows/children — NOT for file_type anymore.)"""
        return main.find("ul", recursive=False) if main else None

    def _peek_breadcrumb(self, base: str) -> Optional[Tuple[str, Optional[str]]]:
        """Open another page JUST to read its own breadcrumb, returning
        (its_abs_path, its_parent_path). Memoized — a target may be linked from
        several places, but its breadcrumb never changes between peeks."""
        if base in self._breadcrumb_cache:
            return self._breadcrumb_cache[base]
        fp = self.files_by_basename.get(base)
        result: Optional[Tuple[str, Optional[str]]] = None
        if fp is not None:
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    soup = BeautifulSoup(f.read(), PARSER)
                segs = self._breadcrumb_segments(soup)
                abs_path = self._page_abs_path(segs)
                result = (abs_path, self._parent_path(abs_path))
            except Exception:
                result = None
        self._breadcrumb_cache[base] = result
        return result

    def _classify_file_type(self, main, is_index: bool, page_abs: str) -> str:
        """FILE axis, decided purely from this file's div.main CONTENT. Rule:
          - no <a> at all in div.main                          -> 'end_path'
          - has <a>, but none is a genuine first-degree child   -> 'end_path'
          - has at least one genuine first-degree child         -> 'intermediate_path'

        For each <a> we decide whether it is a FIRST-DEGREE CHILD of this page:
          * <a href> containing '#'  -> an in-page / cross-ref link: SKIPPED, never
            counts (this is the user's '#' rule).
          * <a name="…/">            -> a navigation FOLDER anchor (its name is a
            path ending in '/'); a hosted child folder, so first-degree child.
          * <a name="…">  (no '/')   -> an in-page BOOKMARK anchor (e.g. a content
            section id like 'S11007…'); NOT a child: SKIPPED. This is the fix —
            previously ANY <a name> wrongly promoted a leaf to intermediate.
          * <a href> (no '#') to a followable page whose OWN breadcrumb names THIS
            page as its immediate parent -> first-degree child.
        Anything else (cross-references, external/dead links, sibling links) is not
        a first-degree child, so the page stays 'end_path'. index.html is root."""
        if is_index:
            return "root_path"
        if main is None:
            return "end_path"
        for a in main.find_all("a"):
            name = a.get("name")
            if name is not None:
                if name.endswith("/"):           # nav folder anchor = hosted child
                    return "intermediate_path"
                continue                          # in-page bookmark anchor: skip
            href = a.get("href")
            if self._has_fragment(href):          # '#' link to current page: skip
                continue
            base = self._resolve_basename(href)
            if not self._is_followable(base):
                continue
            info = self._peek_breadcrumb(base)
            if info is not None and info[1] == page_abs:   # target's parent is us
                return "intermediate_path"
        return "end_path"

    # ---------------------------------------------------------------- parse
    def parse_page(self, file_path: Path, is_index: bool
                   ) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Parse one file -> (page_abs_path, rows, structural_children).

        rows[0] is ALWAYS the page-base row (this page as a node). Its node_type is
        left NULL here and inherited from the parent page's <li> at crawl time.
        structural_children are {basename, node_type, sort_order, ...} pointers to
        deeper pages to open next."""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f.read(), PARSER)

        # find(...) (not CSS .select_one) to avoid the soupsieve dependency.
        main = soup.find("div", class_="main") or soup.body or soup
        segs = self._breadcrumb_segments(soup)
        page_abs = self._page_abs_path(segs)
        file_type = self._classify_file_type(main, is_index, page_abs)
        source_file = str(file_path.resolve())

        h1 = main.find("h1")
        title = (h1.get_text(strip=True) if h1
                 else self._unescape(segs[-1]) if segs else (page_abs or "Root"))

        # Strip dead placeholder links (e.g. "Download .zip for offline use" ->
        # 404.html) so they never end up saved into a car's content HTML.
        if main is not None:
            for a in main.find_all("a"):
                href = a.get("href")
                if href and not self._has_fragment(href):
                    base = Path(urlsplit(href).path).name.lower()
                    if base in ("404.html", "about.html"):
                        a.decompose()

        # Store the raw div.main HTML ONLY for end_path (leaf) pages. Intermediate
        # and root pages are navigation hubs, so their content column stays NULL.
        content = main.decode_contents() if (file_type == "end_path" and main is not None) else None

        rows: List[Dict[str, Any]] = [dict(
            path=page_abs,
            parent_path=(None if is_index else self._parent_path(page_abs)),
            title=title,
            node_type=None,                 # inherited from parent <li> via crawl
            file_type=file_type,            # authoritative
            href=None,
            source_file=source_file,
            sort_order=0,
            depth=page_abs.count("/"),
            content=content,
        )]

        children: List[Dict[str, Any]] = []
        if file_type in ("root_path", "intermediate_path"):
            nav = self._nav_ul(main)
            if nav is not None:
                self._walk(nav, page_abs, page_abs, source_file, rows, children, is_top=True)

        # ---- Broadened discovery (logical fix) -------------------------------
        # A first-degree child page can be expressed as a BARE link in the body
        # (a thin "redirect" page) instead of inside the split-tree <ul>. The
        # nav-only walk above misses those, which orphans the target entirely
        # (e.g. "Labor Times" -> "Labor Times: Other Variant"). So additionally
        # scan EVERY followable, non-fragment <a href> in div.main and queue it
        # as a candidate child.
        #
        # This only affects REACHABILITY. It never decides parentage: each target
        # is placed under whoever its OWN breadcrumb names as parent, and the
        # end_path/intermediate_path label is corrected post-crawl in
        # _reconcile_file_types() from that same breadcrumb relationship — so a
        # genuine cross-reference can never falsely promote a leaf page.
        seen = {c["basename"] for c in children}
        for a in main.find_all("a"):
            if a.get("name") is not None:            # page-less folder anchor
                continue
            href = a.get("href")
            if self._has_fragment(href):             # in-page / cross-ref anchor
                continue
            base = self._resolve_basename(href)
            if self._is_followable(base) and base not in seen:
                seen.add(base)
                children.append(dict(
                    basename=base,
                    node_type=None,                  # no DOM <li> role; derived post-crawl
                    sort_order=10_000 + len(children),
                    href=href,
                    link_text=a.get_text(strip=True),
                    parent_path=page_abs,            # STUB-RECOVERY fallback anchor
                ))

        return page_abs, rows, children

    def _walk(self, ul, page_abs: str, current_base: str, source_file: str,
              rows: List[Dict[str, Any]], children: List[Dict[str, Any]],
              is_top: bool) -> None:
        """DOM walk of one page's split tree (node_type logic unchanged):
            top-level <li>              -> 'root'
            has nested <ul> with <li>   -> 'folder'
            otherwise                   -> 'leaf'
        <a name='…/'> are page-less folder/leaf nodes emitted here. Structural
        <a href='pages/N.html'> leaves are NOT emitted here; they are deferred to
        when the target page is opened (its breadcrumb owns the path), carrying
        only node_type/order downward. Cross-ref / dead / external hrefs are
        emitted as plain DOM leaves so nothing is silently lost."""
        for order, li in enumerate(ul.find_all("li", recursive=False)):
            a = li.find("a", recursive=False)
            if a is None:
                continue

            name = a.get("name")
            href = a.get("href")
            link_text = a.get_text(strip=True)

            sub = li.find("ul", recursive=False)
            has_child_li = sub is not None and sub.find("li", recursive=False) is not None
            node_type = "root" if is_top else ("folder" if has_child_li else "leaf")

            if name is not None:
                # Page-less folder anchor. Fragment is RELATIVE to this page, so the
                # absolute path is page_abs + fragment (matches deeper breadcrumbs).
                rel = self._decode_frag(name)
                node_path = self._norm(f"{page_abs}/{rel}")
                rows.append(self._dom_row(node_path, node_type, None, source_file,
                                          order, fallback_title=link_text))
                if sub is not None:
                    self._walk(sub, page_abs, node_path, source_file, rows, children, is_top=False)
                continue

            base = self._resolve_basename(href)
            if not self._has_fragment(href) and self._is_followable(base):
                # Structural child PAGE: defer the node to its own open.
                # link_text + parent_path let the crawl recover the node under
                # this referrer if the target turns out to be a breadcrumb-less
                # "known-missing" stub (STUB-RECOVERY in the BFS body).
                children.append(dict(basename=base, node_type=node_type,
                                     sort_order=order, href=href,
                                     link_text=link_text, parent_path=current_base))
                if sub is not None:
                    # Rare: a followable leaf that also nests a <ul> on this page.
                    guess = self._norm(f"{current_base}/{self._escape_text(link_text)}")
                    self._walk(sub, page_abs, guess, source_file, rows, children, is_top=False)
            else:
                # Cross-reference / dead / external / unindexed: keep as a DOM leaf.
                node_path = self._norm(f"{current_base}/{self._escape_text(link_text or 'untitled')}")
                rows.append(self._dom_row(node_path, node_type, href, source_file,
                                          order, fallback_title=link_text))
                if sub is not None:
                    self._walk(sub, page_abs, node_path, source_file, rows, children, is_top=False)

    def _dom_row(self, node_path: str, node_type: str, href: Optional[str],
                 source_file: str, order: int, fallback_title: str) -> Dict[str, Any]:
        last = node_path.rsplit("/", 1)[-1] if node_path else node_path
        return dict(
            path=node_path,
            parent_path=self._parent_path(node_path),
            title=self._unescape(last) or fallback_title or "(untitled)",
            node_type=node_type,
            file_type=None,                 # page-less DOM nodes have no file_type
            href=href,
            source_file=source_file,
            sort_order=order,
            depth=node_path.count("/"),
            content=None,
        )

    # ----------------------------------------------------------------- save
    def save_rows(self, rows: List[Dict[str, Any]], conn: sqlite3.Connection) -> int:
        now = datetime.now(timezone.utc).isoformat()
        n = 0
        for r in rows:
            nid = self._hash(r["path"])
            pid = self._hash(r["parent_path"]) if r["parent_path"] is not None else None
            conn.execute("""
                INSERT INTO nodes (id, parent_id, path, title, node_type, file_type,
                                   href, source_file, sort_order, depth, content, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    parent_id   = COALESCE(excluded.parent_id, nodes.parent_id),
                    title       = COALESCE(NULLIF(excluded.title,''), nodes.title),
                    -- file_type / content are set once, by the page-base row, and win.
                    file_type   = COALESCE(excluded.file_type, nodes.file_type),
                    content     = COALESCE(excluded.content,   nodes.content),
                    -- node_type: keep whichever non-NULL DOM label we have.
                    node_type   = COALESCE(excluded.node_type, nodes.node_type),
                    href        = COALESCE(nodes.href, excluded.href),
                    source_file = COALESCE(nodes.source_file, excluded.source_file),
                    sort_order  = excluded.sort_order,
                    depth       = excluded.depth,
                    updated_at  = excluded.updated_at
            """, (nid, pid, r["path"], r["title"], r["node_type"], r["file_type"],
                  r["href"], r["source_file"], r["sort_order"], r["depth"],
                  r["content"], now))
            n += 1
        return n

    # ----------------------------------------------------- resume checkpoint
    def _save_checkpoint(self, conn: sqlite3.Connection, visited: set,
                         queue: deque, processed: int, failed: int,
                         total_nodes: int, done: bool = False) -> None:
        """Atomically persist the crawl frontier so a killed run can resume.
        Written inside the same connection right after a node commit, so the
        snapshot is always consistent with what's already in the nodes table."""
        snap = json.dumps({
            "visited": list(visited),
            "queue": list(queue),
            "processed": processed,
            "failed": failed,
            "total_nodes": total_nodes,
            "model_root": self.model_root,
            "done": done,
        })
        conn.execute(
            "INSERT INTO crawl_state(k, v) VALUES('snapshot', ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (snap,))
        conn.commit()

    def _load_checkpoint(self, conn: sqlite3.Connection):
        """Return (visited, queue, processed, failed, total_nodes) if a
        resumable, not-yet-finished snapshot exists, else None."""
        row = conn.execute(
            "SELECT v FROM crawl_state WHERE k = 'snapshot'").fetchone()
        if not row:
            return None
        try:
            s = json.loads(row[0])
        except Exception:
            return None
        if s.get("done"):
            return None  # already finished; nothing to resume
        self.model_root = s.get("model_root", self.model_root)
        return (set(s["visited"]), deque(s["queue"]),
                s["processed"], s["failed"], s["total_nodes"])

    # ---------------------------------------------------------------- crawl
    def crawl(self, cancel_event=None) -> int:
        """Crawl to completion and return the page count. If cancel_event is set
        partway through, the current frontier is checkpointed and CrawlPaused is
        raised so a later run can resume from exactly here."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")

        resumed = self._load_checkpoint(conn)
        if resumed is not None:
            visited, queue, processed, failed, total_nodes = resumed
            with print_lock:
                print(f"⏯️  Resuming crawl: {processed} pages already done, "
                      f"{len(queue)} queued, model root "
                      f"{self._unescape(self.model_root) or '(unknown)'}")
        else:
            # Fresh start. Establish the model root from index.html's last
            # breadcrumb part, then seed the BFS with the index page itself.
            with open(self.index_file, "r", encoding="utf-8", errors="replace") as f:
                idx_soup = BeautifulSoup(f.read(), PARSER)
            idx_segs = self._breadcrumb_segments(idx_soup)
            self.model_root = idx_segs[-1] if idx_segs else ""
            with print_lock:
                print(f"🌱 Model root: {self._unescape(self.model_root) or '(unknown)'}")

            visited = {self.index_file.name.lower()}
            queue = deque()
            processed = failed = total_nodes = 0

            # 1) the index page itself (root_path; no parent <li> to inherit from).
            try:
                _, rows, children = self.parse_page(self.index_file, is_index=True)
                total_nodes += self.save_rows(rows, conn)
                processed += 1
                queue.extend(children)
            except Exception as e:
                failed += 1
                with print_lock:
                    print(f"❌ index {self.index_file}: {e}")
            self._save_checkpoint(conn, visited, queue, processed, failed, total_nodes)

        # 2) BFS over structural child pages.
        skipped_excluded = 0
        while queue:
            # Cooperative cancel: checkpoint NOW (commit nodes + frontier together)
            # and bail out so pressing Start later resumes from this exact spot.
            if cancel_event is not None and cancel_event.is_set():
                conn.commit()
                self._save_checkpoint(conn, visited, queue,
                                      processed, failed, total_nodes)
                conn.close()
                with print_lock:
                    print(f"\n⏸️  Paused at {processed} pages "
                          f"({len(queue)} still queued) — checkpoint saved.")
                raise CrawlPaused()

            c = queue.popleft()
            base = c["basename"]
            if base in visited:
                continue
            visited.add(base)
            fp = self.files_by_basename.get(base)
            if fp is None:
                with print_lock:
                    print(f"⚠️ structural link '{base}' not found in index — skipped")
                continue
            try:
                _, rows, grandchildren = self.parse_page(fp, is_index=False)
                # Prune excluded aggregate subtrees (e.g. the duplicate "single
                # page" branch): skip saving the node AND skip enqueuing its
                # children, so the whole subtree never enters the warehouse. Its
                # descendant pages remain reachable through the canonical tree.
                if rows and rows[0].get("title") in EXCLUDED_PAGE_TITLES:
                    visited.add(base)
                    skipped_excluded += 1
                    continue
                # Inherit node_type / sort_order from the parent <li> onto page-base.
                pb = rows[0]
                pb["node_type"] = c["node_type"]
                pb["sort_order"] = c["sort_order"]
                if c.get("href"):
                    pb["href"] = c["href"]
                # STUB-RECOVERY: a "known-missing" target page carries no
                # breadcrumb, so parse_page yields an empty page_abs and the row
                # would otherwise be saved as a junk title="Root", path="" node
                # (all such stubs collapsing onto the same id). Re-anchor it under
                # the referring parent using the link text, so the node keeps its
                # real title and position in the tree. Content stays whatever the
                # stub held (the "known-missing" notice), so the leaf is visible
                # and honestly flags the gap instead of vanishing.
                if not pb.get("path"):
                    parent = c.get("parent_path")
                    ltext = c.get("link_text")
                    if parent is not None and ltext:
                        node_path = self._norm(f"{parent}/{self._escape_text(ltext)}")
                        pb["path"] = node_path
                        pb["parent_path"] = self._parent_path(node_path)
                        pb["title"] = ltext
                        pb["depth"] = node_path.count("/")
                        pb["file_type"] = "end_path"
                    else:
                        # No anchor to recover under: drop the junk row entirely
                        # rather than persist an empty-path "Root".
                        raise _StubSkip()
                total_nodes += self.save_rows(rows, conn)
                processed += 1
                queue.extend(grandchildren)
                if processed % CHECKPOINT_EVERY == 0:
                    # Commit nodes THEN snapshot the frontier in the same conn, so
                    # the resume point can never be ahead of the persisted rows.
                    conn.commit()
                    self._save_checkpoint(conn, visited, queue,
                                          processed, failed, total_nodes)
                    with print_lock:
                        print(f"  …{processed} pages, {total_nodes} node rows, "
                              f"{len(queue)} queued (checkpointed)")
            except _StubSkip:
                # Breadcrumb-less stub with no recovery anchor: silently drop.
                continue
            except Exception as e:
                failed += 1
                with print_lock:
                    print(f"❌ {fp}: {e}")

        conn.commit()
        promoted = self._reconcile_file_types(conn)
        conn.commit()
        roots_n = self._assign_root_order(conn)
        conn.commit()
        # Mark the crawl finished so a future run skips straight past it.
        self._save_checkpoint(conn, visited, queue, processed, failed,
                              total_nodes, done=True)
        conn.execute("PRAGMA optimize;")
        conn.close()

        with print_lock:
            print("\n" + "=" * 70)
            print("📊 SUMMARY")
            print(f"✅ Pages processed : {processed}")
            print(f"❌ Failed          : {failed}")
            print(f"🧩 Node rows upserted (incl. dedup): {total_nodes}")
            print(f"🔁 Promoted end→intermediate (breadcrumb): {promoted}")
            print(f"🌱 Root nodes ordered: {roots_n}")
            print(f"🚫 Excluded subtrees pruned: {skipped_excluded}")
            print(f"💾 Database        : {self.db_path}")
        return processed

    def _reconcile_file_types(self, conn: sqlite3.Connection) -> int:
        """Breadcrumb-driven correction of the FILE axis (the logical fix).

        Parse-time classification calls a page 'end_path' when it has no
        navigation <ul> of its own. That is a DOM-SHAPE proxy for "is a parent",
        and it is wrong for a thin page whose only child is a bare body link
        (e.g. 'Labor Times' -> 'Labor Times: Other Variant'). The breadcrumb is
        the source of truth: if ANY real page row names this page as its
        first-degree parent (child.parent_id == this.id), then this page is an
        intermediate, not a leaf.

        So, globally:
          - promote any 'end_path' page that turns out to parent a real page,
          - drop its now-meaningless placeholder content (only leaves keep content),
          - upgrade a stale 'leaf' node_type to 'folder'.

        A genuine cross-reference never triggers this, because the linked
        target's OWN breadcrumb parent is some other page, not this one — so it
        is not joined here.
        """
        cur = conn.execute("""
            UPDATE nodes
               SET file_type = 'intermediate_path',
                   content   = NULL,
                   node_type = CASE
                                   WHEN node_type IS NULL OR node_type = 'leaf'
                                   THEN 'folder' ELSE node_type
                               END
             WHERE file_type = 'end_path'
               AND id IN (
                   SELECT DISTINCT parent.id
                     FROM nodes AS parent
                     JOIN nodes AS child ON child.parent_id = parent.id
                    WHERE child.file_type IS NOT NULL      -- child is a real page
               );
        """)
        promoted = cur.rowcount

        # Pages discovered via a bare body link have no DOM <li> to inherit a
        # node_type from, so their page-base row carries node_type = NULL. Give
        # them a concrete DOM role consistent with their realized file_type.
        # (root_path rows are intentionally left as-is, matching prior behavior.)
        conn.execute("""
            UPDATE nodes
               SET node_type = CASE WHEN file_type = 'end_path'
                                    THEN 'leaf' ELSE 'folder' END
             WHERE node_type IS NULL
               AND file_type IN ('end_path', 'intermediate_path');
        """)

        # Final invariant: ANY node that actually parents a child is a folder.
        # The promotion above only rescues end_path pages; a page already
        # classified intermediate_path (it has <a name="…/"> hub anchors) but
        # whose page-base row inherited node_type='leaf' from a parent <li>
        # with no nested <ul> (Toyota lists a hub page as a bare link) was
        # never reconciled — leaving ~700 nodes/car as leaf while holding
        # children. car_view serves by content-presence so pages still render,
        # but the DOM role was a lie; anything trusting node_type broke on it.
        conn.execute("""
            UPDATE nodes
               SET node_type = 'folder'
             WHERE node_type = 'leaf'
               AND EXISTS (SELECT 1 FROM nodes ch WHERE ch.parent_id = nodes.id);
        """)
        return promoted

    def _assign_root_order(self, conn: sqlite3.Connection) -> int:
        roots = conn.execute(
            "SELECT id FROM nodes WHERE node_type = 'root' ORDER BY path"
        ).fetchall()
        conn.execute("UPDATE nodes SET root_order = NULL WHERE node_type != 'root' OR node_type IS NULL")
        for order, (rid,) in enumerate(roots):
            conn.execute("UPDATE nodes SET root_order = ? WHERE id = ?", (order, rid))
        return len(roots)


# ====================================================================== ZIP-LEVEL LEDGER

class ProcessingLedger:
    """Tracks per-zip processing status in the backend db.sqlite3 so a re-run
    skips zips that are already fully done and resumes the rest. Identity is
    (name, size, mtime): if a zip is replaced with a newer/edited file, its row
    no longer matches 'completed' and it is reprocessed. All writes go through a
    single process-wide lock because worker threads share the SQLite file."""

    def __init__(self, backend_db: Path):
        self.backend_db = str(backend_db)
        with ledger_lock:
            conn = sqlite3.connect(self.backend_db)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processing_status (
                    zip_name        TEXT PRIMARY KEY,
                    zip_size        INTEGER,
                    zip_mtime       REAL,
                    status          TEXT,      -- 'in_progress' | 'completed' | 'failed'
                    pages_processed INTEGER,
                    started_at      TEXT,
                    finished_at     TEXT,
                    error           TEXT
                )
            """)
            conn.commit()
            conn.close()

    @staticmethod
    def _sig(zip_path: Path) -> Tuple[int, float]:
        st = zip_path.stat()
        return st.st_size, st.st_mtime

    def is_completed(self, zip_path: Path) -> bool:
        """True only if this exact zip (same size+mtime) is recorded completed."""
        size, mtime = self._sig(zip_path)
        with ledger_lock:
            conn = sqlite3.connect(self.backend_db)
            row = conn.execute(
                "SELECT status, zip_size, zip_mtime FROM processing_status "
                "WHERE zip_name = ?", (zip_path.name,)).fetchone()
            conn.close()
        if not row:
            return False
        status, size_db, mtime_db = row
        # mtime compared with tolerance (FS timestamp precision varies).
        return (status == "completed" and size_db == size
                and abs((mtime_db or 0) - mtime) < 1.0)

    def mark_start(self, zip_path: Path) -> None:
        size, mtime = self._sig(zip_path)
        now = datetime.now(timezone.utc).isoformat()
        with ledger_lock:
            conn = sqlite3.connect(self.backend_db)
            conn.execute("""
                INSERT INTO processing_status
                    (zip_name, zip_size, zip_mtime, status, pages_processed,
                     started_at, finished_at, error)
                VALUES (?,?,?,'in_progress',0,?,NULL,NULL)
                ON CONFLICT(zip_name) DO UPDATE SET
                    zip_size=excluded.zip_size, zip_mtime=excluded.zip_mtime,
                    status='in_progress', started_at=excluded.started_at,
                    finished_at=NULL, error=NULL
            """, (zip_path.name, size, mtime, now))
            conn.commit()
            conn.close()

    def mark_done(self, zip_path: Path, pages: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with ledger_lock:
            conn = sqlite3.connect(self.backend_db)
            conn.execute(
                "UPDATE processing_status SET status='completed', "
                "pages_processed=?, finished_at=?, error=NULL WHERE zip_name=?",
                (pages, now, zip_path.name))
            conn.commit()
            conn.close()

    def mark_failed(self, zip_path: Path, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with ledger_lock:
            conn = sqlite3.connect(self.backend_db)
            conn.execute(
                "UPDATE processing_status SET status='failed', "
                "finished_at=?, error=? WHERE zip_name=?",
                (now, str(error)[:2000], zip_path.name))
            conn.commit()
            conn.close()


# ====================================================================== MAIN AUTOMATED PROCESS

def zip_extract_dir(zip_path: Path, extract_to: Path) -> Optional[Path]:
    """Compute WHERE a zip would extract to, WITHOUT extracting it. Mirrors the
    root-folder logic in extract_zip so we can detect an already-extracted folder
    and skip re-unzipping on resume."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            all_names = zip_ref.namelist()
    except Exception:
        return None
    if not all_names:
        return None
    common_prefix = os.path.commonprefix(all_names)
    if common_prefix and common_prefix.endswith('/'):
        return extract_to / common_prefix.rstrip('/')
    return extract_to / zip_path.stem


def has_resumable_checkpoint(db_path: Path) -> bool:
    """True if this car's db holds a crawl checkpoint that is NOT yet finished —
    i.e. the HTML was already extracted and parsing can continue mid-crawl."""
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT v FROM crawl_state WHERE k = 'snapshot'").fetchone()
        conn.close()
    except Exception:
        return False
    if not row:
        return False
    try:
        return not json.loads(row[0]).get("done", False)
    except Exception:
        return False


def extract_zip(zip_path: Path, extract_to: Path) -> Optional[Path]:
    """Extract a zip file and return the path to the extracted folder."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Extract all files
            zip_ref.extractall(extract_to)
            
            # Determine the root folder name from the zip contents
            all_names = zip_ref.namelist()
            if not all_names:
                with print_lock:
                    print(f"⚠️ Zip file is empty: {zip_path.name}")
                return None
            
            # Find the common prefix directory
            common_prefix = os.path.commonprefix(all_names)
            if common_prefix and common_prefix.endswith('/'):
                # There's a root directory in the zip
                root_dir = extract_to / common_prefix.rstrip('/')
            else:
                # Files are at root level, use the zip name without extension
                root_dir = extract_to / zip_path.stem
            
            with print_lock:
                print(f"📦 Extracted: {zip_path.name} -> {root_dir}")
            return root_dir
            
    except Exception as e:
        with print_lock:
            print(f"❌ Failed to extract {zip_path.name}: {e}")
        return None


def parse_car_info(db_name: str) -> Tuple[str, int, str]:
    """Parse brand, year, and car name from database filename.
    Example: '2025 Toyota Land Cruiser Base.db' -> ('Toyota', 2025, 'Land Cruiser Base')"""
    # Remove .db extension
    name = db_name.replace('.db', '')
    
    # Extract year (first 4 digits)
    year_match = re.match(r'^(\d{4})\s+(.+)$', name)
    if year_match:
        year = int(year_match.group(1))
        rest = year_match.group(2)
    else:
        year = 2025  # Default fallback
        rest = name
    
    # Extract brand (first word after year)
    parts = rest.split(' ', 1)
    if len(parts) >= 2:
        brand = parts[0]
        car_name = parts[1]
    else:
        brand = rest
        car_name = rest
    
    return brand, year, car_name


# The fleet's original naming convention keeps the plain car name as the
# warehouse stem for this model year; other years get a " (<year>)" suffix so
# e.g. the 2023 and 2025 "Corolla Cross LE, FWD" manuals coexist as separate
# cars (the stem doubles as catalog car_name and RAG car_stem — it must be
# unique per vehicle, and year alone lives in the catalog's year column).
DEFAULT_STEM_YEAR = 2025


def warehouse_stem(car_name: str, year: int) -> str:
    """Warehouse filename stem (== catalog car_name) for a parsed car."""
    if year and year != DEFAULT_STEM_YEAR:
        return f"{car_name} ({year})"
    return car_name


def process_single_zip(zip_path: Path, backend_dir: Path, db_warehouse: Path,
                       static_warehouse: Path, current_dir: Path,
                       ledger: "ProcessingLedger", cancel_event=None,
                       force: bool = False) -> Optional[Dict]:
    """Process a single zip file - designed for parallel execution.

    Idempotent: a zip already recorded 'completed' (same size+mtime) is skipped
    entirely. Otherwise the per-car crawl resumes from its last checkpoint, so an
    interrupted run picks up mid-manual instead of restarting from scratch.

    force=True ignores 'completed' and deletes the old car .db so the manual is
    regenerated cleanly with the current parser logic."""
    # ---- skip fully-completed zips (unless forcing a reprocess) -----------
    if not force and ledger.is_completed(zip_path):
        with print_lock:
            print(f"⏭️  Skipping (already completed): {zip_path.name}")
        return None

    # ---- force: wipe the stale car db so regeneration starts fresh --------
    if force:
        db_name = zip_path.name.replace("KGTV ", "").replace(".zip", ".db")
        for suffix in ("", "-wal", "-shm"):
            stale = current_dir / (db_name + suffix)
            try:
                if stale.exists():
                    stale.unlink()
            except OSError as e:
                with print_lock:
                    print(f"⚠️ could not remove old db {stale}: {e}")

    # ---- if a pause was requested before this zip even started, do nothing.
    # Status stays untouched (or 'in_progress' if partially done) so a later run
    # resumes it. This is what stops NEW zips from starting after Stop is pressed.
    if cancel_event is not None and cancel_event.is_set():
        with print_lock:
            print(f"⏸️  Not starting (paused): {zip_path.name}")
        return None

    with print_lock:
        print(f"\n{'='*70}")
        print(f"🔄 Processing: {zip_path.name}")
        print("=" * 70)
    ledger.mark_start(zip_path)

    try:
        return _process_single_zip_inner(
            zip_path, backend_dir, db_warehouse, static_warehouse,
            current_dir, ledger, cancel_event)
    except CrawlPaused:
        # Not a failure: checkpoint is saved, status left 'in_progress' so the
        # next run resumes this car from where it stopped.
        with print_lock:
            print(f"⏸️  Paused: {zip_path.name} (will resume on next run)")
        return None
    except Exception as e:
        ledger.mark_failed(zip_path, str(e))
        with print_lock:
            print(f"❌ Error processing {zip_path.name}: {e}")
        return None


def _publish_images(images_source, images_dest, static_warehouse):
    """Give a car its own image folder without duplicating bytes on disk.

    Image filenames are Toyota's global asset IDs, so the same name always
    carries the same bytes across every car. Each distinct image is therefore
    written once into ``static_warehouse/_store/`` and every car folder gets a
    hardlink to it - N cars sharing an image cost one copy instead of N.

    The store lives inside static_warehouse on purpose: hardlinks only work
    within a single filesystem. Files are written to a temp name and renamed
    into place, so a shared inode is never modified after publication and
    readers always see a complete file.

    Returns (new, linked): images copied for the first time, and images that
    were already in the store.
    """
    store = static_warehouse / "_store"
    store.mkdir(parents=True, exist_ok=True)

    if images_dest.exists():
        shutil.rmtree(images_dest)
    images_dest.mkdir(parents=True)

    new = linked = 0
    for src in sorted(images_source.iterdir()):
        if not src.is_file():
            continue
        canon = store / src.name
        if canon.exists():
            linked += 1
        else:
            tmp = store / f".{src.name}.{os.getpid()}.tmp"
            shutil.copy2(src, tmp)
            os.replace(tmp, canon)
            new += 1
        try:
            os.link(canon, images_dest / src.name)
        except FileExistsError:
            pass
    return new, linked


def _process_single_zip_inner(zip_path: Path, backend_dir: Path, db_warehouse: Path,
                              static_warehouse: Path, current_dir: Path,
                              ledger: "ProcessingLedger", cancel_event=None) -> Optional[Dict]:
    # The per-car db lives next to the zips; its name is derived from the zip,
    # independent of extraction, so we can check for a checkpoint up front.
    db_name = zip_path.name.replace("KGTV ", "").replace(".zip", ".db")
    db_path = current_dir / db_name

    # ---- Resume fast-path: if a not-yet-finished checkpoint exists AND the
    # already-extracted folder is still on disk, skip unzipping entirely and go
    # straight back to crawling. A checkpoint implies the HTML was fully extracted
    # in a previous run, so re-unzipping would be wasted work.
    extract_dir = None
    expected_dir = zip_extract_dir(zip_path, current_dir)
    if (has_resumable_checkpoint(db_path) and expected_dir is not None
            and expected_dir.exists()
            and next(expected_dir.rglob("index.html"), None) is not None):
        extract_dir = expected_dir
        with print_lock:
            print(f"⏩ Checkpoint found — skipping unzip, reusing: {extract_dir}")
    else:
        # Fresh (or extracted folder missing): extract the zip.
        extract_dir = extract_zip(zip_path, current_dir)
        if extract_dir is None:
            ledger.mark_failed(zip_path, "extraction failed / empty zip")
            return None

    # Find index.html in extracted folder (search recursively if needed)
    index_file = None
    for html_file in extract_dir.rglob("index.html"):
        index_file = html_file
        break
    
    if index_file is None:
        with print_lock:
            print(f"⚠️ No index.html found in {extract_dir}, skipping...")
        ledger.mark_failed(zip_path, "no index.html found")
        return None
    
    with print_lock:
        print(f"📄 Found index.html at: {index_file}")

    # Parse car info from database name (db_name/db_path computed above).
    brand, year, car_name = parse_car_info(db_name)
    stem = warehouse_stem(car_name, year)
    with print_lock:
        print(f"🚗 Car info: {brand} {year} {car_name} (stem: {stem})")
    
    # Run HTML parser
    with print_lock:
        print(f"\n🔧 Parsing HTML for {db_name}...")
    
    parser = LogicalHTMLParser(
        html_dir=str(extract_dir),
        index_file=str(index_file),
        db_path=str(db_path)
    )
    pages = parser.crawl(cancel_event)

    # Copy database to warehouse (renamed to the stem — no KGTV prefix, and
    # the year only appears in the stem for non-default model years).
    final_db_name = f"{stem}.db"
    final_db_path = db_warehouse / final_db_name

    if db_path.exists():
        shutil.copy2(db_path, final_db_path)
        with print_lock:
            print(f"📁 Copied database to: {final_db_path}")
    else:
        with print_lock:
            print(f"⚠️ Database not found: {db_path}")
        ledger.mark_failed(zip_path, "car database not produced")
        return None
    
    # Publish images into the static warehouse. Each distinct image is stored
    # once under _store/ and hardlinked into this car's folder, so cars that
    # share a diagram share the bytes too. Paths are unchanged: the manual
    # still references /media/<car>/<file> exactly as before.
    images_source = extract_dir / "images"
    if not (images_source.exists() and images_source.is_dir()):
        images_source = next(
            (d for d in extract_dir.rglob("images") if d.is_dir()), None)

    if images_source:
        images_dest = static_warehouse / stem
        new, linked = _publish_images(images_source, images_dest,
                                      static_warehouse)
        with print_lock:
            print(f"\U0001f4c1 Images for {stem}: {linked} shared, "
                  f"{new} new -> {images_dest}")
    else:
        with print_lock:
            print(f"\u26a0\ufe0f No images folder found in {extract_dir}")
    
    # Optional: Cleanup extracted folder
    # shutil.rmtree(extract_dir)
    # with print_lock:
    #     print(f"🧹 Cleaned up: {extract_dir}")
    
    # Mark this zip fully completed so future runs skip it.
    ledger.mark_done(zip_path, pages)
    with print_lock:
        print(f"🏁 Completed {zip_path.name}: {pages} pages")

    # Return car info for backend update. car_name is the STEM: the catalog's
    # car_name column must equal the warehouse filename stem (that invariant is
    # what makes brand/year/name links and RAG car_stem resolve), so a
    # year-suffixed stem is carried through to the catalog verbatim while the
    # year column keeps the numeric year.
    return {
        'brand': brand,
        'year': year,
        'car_name': stem,
        # Always use POSIX '/' separators so the address is portable: the frontend
        # may serve from Linux/macOS where a Windows '\' is a literal filename char
        # (causing 404s). '/' is valid on Windows too, so this is safe everywhere.
        'db_address': f"./Database_warehouse/{final_db_name}"
    }


def process_all_zips(backend_path: str, max_workers: int = None,
                     zips_dir: str = None, cancel_event=None, force: bool = False):
    """Main function to process all KGTV zip files in parallel.

    zips_dir: folder to search for 'KGTV *.zip' and to use as the extraction /
    intermediate working directory. Defaults to the current working directory so
    existing command-line behavior is unchanged.

    cancel_event: optional threading.Event. When set, in-flight crawls checkpoint
    and stop, and no new zips are started. Re-running resumes from the checkpoints.

    force: when True, ignore the 'completed' ledger status and REPROCESS every zip
    from scratch (the old car .db is deleted first for a clean regenerate). Use
    this after changing the parser logic.
    """
    backend_dir = Path(backend_path).resolve()
    current_dir = Path(zips_dir).resolve() if zips_dir else Path.cwd()
    
    # Check if backend directory exists
    if not backend_dir.exists():
        print(f"❌ Error: Backend directory '{backend_path}' does not exist.")
        sys.exit(1)
    
    # Check for db.sqlite3 in backend
    db_backend = backend_dir / "db.sqlite3"
    if not db_backend.exists():
        print(f"❌ Error: Database file '{db_backend}' does not exist.")
        sys.exit(1)
    
    # Create warehouse directories
    db_warehouse = backend_dir / "Database_warehouse"
    static_warehouse = backend_dir / "static_warehouse"
    db_warehouse.mkdir(exist_ok=True)
    static_warehouse.mkdir(exist_ok=True)

    # Zip-level progress ledger (lives in the backend db.sqlite3).
    ledger = ProcessingLedger(db_backend)
    
    print("=" * 70)
    print("🚀 Starting Automated HTML Parser (Parallel)")
    print(f"📁 Backend directory: {backend_dir}")
    print(f"💾 Backend database: {db_backend}")
    print(f"📂 Database warehouse: {db_warehouse}")
    print(f"📂 Static warehouse: {static_warehouse}")
    print(f"⚡ Max workers: {max_workers}")
    print("=" * 70)
    
    # Find all KGTV zip files
    all_zip_files = list(current_dir.glob("KGTV *.zip"))

    if not all_zip_files:
        print("❌ No KGTV *.zip files found in current directory.")
        print(f"   Current directory: {current_dir}")
        sys.exit(1)

    # Split into already-done vs to-do so finished zips are never reprocessed.
    # With force=True, nothing is treated as done -> every zip is reprocessed.
    if force:
        zip_files = list(all_zip_files)
        skipped = []
    else:
        zip_files = [z for z in all_zip_files if not ledger.is_completed(z)]
        skipped = [z for z in all_zip_files if z not in zip_files]

    if force:
        print(f"\n🔁 FORCE reprocess: regenerating all {len(all_zip_files)} zip(s) "
              f"from scratch (ignoring 'completed' status).")
    print(f"\n📦 Found {len(all_zip_files)} zip file(s): "
          f"{len(skipped)} already completed, {len(zip_files)} to process.")
    for zf in skipped:
        print(f"   ⏭️  done : {zf.name}")
    for zf in zip_files:
        print(f"   ▶️  todo : {zf.name}")

    if not zip_files:
        print("\n✅ Nothing to do — all zips already processed.")
        return

    if max_workers is None:
        max_workers = len(zip_files)

    print(f"\n⚡ Processing {len(zip_files)} zip files with {max_workers} parallel workers...")
    
    # Process zips in parallel
    processed_cars = []
    failed_zips = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_zip = {
            executor.submit(process_single_zip, zip_path, backend_dir, db_warehouse,
                          static_warehouse, current_dir, ledger, cancel_event,
                          force): zip_path
            for zip_path in zip_files
        }

        # Collect results as they complete
        for future in as_completed(future_to_zip):
            zip_path = future_to_zip[future]
            try:
                result = future.result()
                if result:
                    processed_cars.append(result)
                    with print_lock:
                        print(f"✅ Completed: {zip_path.name}")
                else:
                    # None can mean paused/skipped (not failures). Only count it as
                    # failed if the ledger actually recorded a failure for it.
                    if not (cancel_event is not None and cancel_event.is_set()):
                        failed_zips.append(zip_path.name)
                        with print_lock:
                            print(f"❌ Failed: {zip_path.name}")
            except Exception as e:
                failed_zips.append(zip_path.name)
                with print_lock:
                    print(f"❌ Error processing {zip_path.name}: {e}")

    if cancel_event is not None and cancel_event.is_set():
        with print_lock:
            print("\n⏸️  Paused by user. Re-run to resume from the last checkpoint.")
    
    # Update backend database (single-threaded to avoid locking issues)
    print(f"\n{'='*70}")
    print("💾 Updating backend database...")
    print("=" * 70)
    
    if processed_cars:
        try:
            conn = sqlite3.connect(db_backend)
            cursor = conn.cursor()
            
            # Ensure main_db table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS main_db (
                    id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    brand_name  TEXT NOT NULL,
                    year        INTEGER NOT NULL,
                    db_address  TEXT NOT NULL,
                    car_name    TEXT NOT NULL
                )
            """)
            
            # Insert records
            inserted = 0
            updated = 0
            for car in processed_cars:
                # Check if car already exists
                cursor.execute(
                    "SELECT id FROM main_db WHERE brand_name = ? AND year = ? AND car_name = ?",
                    (car['brand'], car['year'], car['car_name'])
                )
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing record
                    cursor.execute(
                        """UPDATE main_db 
                           SET db_address = ? 
                           WHERE brand_name = ? AND year = ? AND car_name = ?""",
                        (car['db_address'], car['brand'], car['year'], car['car_name'])
                    )
                    updated += 1
                    with print_lock:
                        print(f"🔄 Updated: {car['brand']} {car['year']} {car['car_name']}")
                else:
                    # Insert new record
                    cursor.execute(
                        """INSERT INTO main_db (brand_name, year, db_address, car_name)
                           VALUES (?, ?, ?, ?)""",
                        (car['brand'], car['year'], car['db_address'], car['car_name'])
                    )
                    inserted += 1
                    with print_lock:
                        print(f"➕ Added: {car['brand']} {car['year']} {car['car_name']}")
            
            conn.commit()
            conn.close()
            print(f"\n✅ Backend database updated: {inserted} new, {updated} updated")
            
        except Exception as e:
            print(f"❌ Failed to update backend database: {e}")
            print(f"   Error details: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        print("⚠️ No cars were processed successfully.")
    
    # Final summary
    print("\n" + "=" * 70)
    print("🎉 COMPLETE!")
    print("=" * 70)
    print(f"✅ Successfully processed: {len(processed_cars)} car(s)")
    print(f"❌ Failed: {len(failed_zips)} zip(s)")
    if failed_zips:
        print(f"   Failed zips: {', '.join(failed_zips)}")
    print(f"📂 Database warehouse: {db_warehouse}")
    print(f"📂 Static warehouse: {static_warehouse}")
    print(f"💾 Backend database: {db_backend}")
    print("\n📋 Processed cars:")
    for car in processed_cars:
        print(f"   - {car['brand']} {car['year']} {car['car_name']}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Automated HTML parser for KGTV car data (parallel processing)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
USAGE:
  python htmlparser_logical.py "path/to/backend_folder"
  python htmlparser_logical.py "path/to/backend_folder" --workers 8

This will:
  1. Extract all KGTV *.zip files in the current directory (parallel)
  2. Parse each extracted HTML folder into a database (parallel)
  3. Copy databases to Database_warehouse/ (renamed without prefix/year)
  4. Copy images folders to static_warehouse/ (renamed to match)
  5. Update backend db.sqlite3 with car information

EXAMPLES:
  python htmlparser_logical.py "C:\\MyProject\\backend"
  python htmlparser_logical.py "C:\\MyProject\\backend" --workers 10
        """
    )
    
    parser.add_argument(
        "backend_folder",
        type=str,
        help="Path to the backend folder containing db.sqlite3"
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: 5)"
    )

    parser.add_argument(
        "--zips-dir",
        type=str,
        default=None,
        help="Folder containing the KGTV *.zip files "
             "(default: current working directory)"
    )

    parser.add_argument(
        "--force", "--reprocess",
        dest="force",
        action="store_true",
        help="Reprocess every zip from scratch, ignoring 'completed' status "
             "(deletes the old car .db first). Use after changing parser logic."
    )

    # Windows consoles default to cp1252, which cannot encode the emoji used in
    # the progress output. Force UTF-8 so direct command-line runs don't crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parser.parse_args()

    process_all_zips(args.backend_folder, args.workers, args.zips_dir,
                     force=args.force)


if __name__ == "__main__":
    main()