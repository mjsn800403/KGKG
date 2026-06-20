# htmlparser_logical.py
#
# Breadcrumb-driven, link-crawled parser with automated zip processing.
# 
# USAGE:
#   python htmlparser_logical.py "path/to/backend_folder"
#
# This will:
#   1. Extract all LEMON *.zip files in the current directory (parallel)
#   2. Parse each extracted HTML folder into a database (parallel)
#   3. Copy databases to Database_warehouse/ (renamed without prefix/year)
#   4. Copy images folders to static_warehouse/ (renamed to match)
#   5. Update backend db.sqlite3 with car information

import re
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

# Thread-safe print lock
print_lock = threading.Lock()


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
        return [self._escape_text(a.get_text(strip=True))
                for a in soup.select("a.breadcrumb-part")]

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
        """FILE axis, decided purely from this file's div.main CONTENT — not its
        DOM shape. Rule:
          - no <a> at all in div.main                          -> 'end_path'
          - has <a>, but none is a genuine first-degree child   -> 'end_path'
          - has at least one genuine first-degree child         -> 'intermediate_path'
        A link is a genuine first-degree child if either:
          (a) it is a page-less folder anchor (<a name='…/'>) — by construction it
              nests directly under this page, or
          (b) it is a followable <a href> whose OWN breadcrumb names THIS page's
              abs path as its immediate parent (checked by peeking at the target
              file right now — every html file already exists on disk, so we never
              need to wait for the rest of the crawl).
        A cross-reference to a page that belongs elsewhere in the tree (its
        breadcrumb parent is something else) never satisfies (b), so it can never
        falsely promote a leaf. The provided index.html is always 'root_path'."""
        if is_index:
            return "root_path"
        if main is None:
            return "end_path"
        for a in main.find_all("a"):
            if a.get("name") is not None:
                return "intermediate_path"
            href = a.get("href")
            if self._has_fragment(href):
                continue
            base = self._resolve_basename(href)
            if not self._is_followable(base):
                continue
            info = self._peek_breadcrumb(base)
            if info is not None and info[1] == page_abs:
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

        main = soup.select_one("div.main") or soup.body or soup
        segs = self._breadcrumb_segments(soup)
        page_abs = self._page_abs_path(segs)
        file_type = self._classify_file_type(main, is_index, page_abs)
        source_file = str(file_path.resolve())

        h1 = main.find("h1")
        title = (h1.get_text(strip=True) if h1
                 else self._unescape(segs[-1]) if segs else (page_abs or "Root"))

        content = main.decode_contents() if (file_type == "end_path" and main) else None

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
                children.append(dict(basename=base, node_type=node_type,
                                     sort_order=order, href=href))
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

    # ---------------------------------------------------------------- crawl
    def crawl(self) -> None:
        # Establish the model root from index.html's last breadcrumb part.
        with open(self.index_file, "r", encoding="utf-8", errors="replace") as f:
            idx_soup = BeautifulSoup(f.read(), PARSER)
        idx_segs = self._breadcrumb_segments(idx_soup)
        self.model_root = idx_segs[-1] if idx_segs else ""
        with print_lock:
            print(f"🌱 Model root: {self._unescape(self.model_root) or '(unknown)'}")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")

        visited = {self.index_file.name.lower()}
        queue: deque = deque()
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

        # 2) BFS over structural child pages.
        while queue:
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
                # Inherit node_type / sort_order from the parent <li> onto page-base.
                pb = rows[0]
                pb["node_type"] = c["node_type"]
                pb["sort_order"] = c["sort_order"]
                if c.get("href"):
                    pb["href"] = c["href"]
                total_nodes += self.save_rows(rows, conn)
                processed += 1
                queue.extend(grandchildren)
                if processed % 100 == 0:
                    conn.commit()
                    with print_lock:
                        print(f"  …{processed} pages, {total_nodes} node rows, {len(queue)} queued")
            except Exception as e:
                failed += 1
                with print_lock:
                    print(f"❌ {fp}: {e}")

        conn.commit()
        promoted = self._reconcile_file_types(conn)
        conn.commit()
        roots_n = self._assign_root_order(conn)
        conn.commit()
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
            print(f"💾 Database        : {self.db_path}")

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
          - drop its now-meaningless placeholder content,
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
        return promoted

    def _assign_root_order(self, conn: sqlite3.Connection) -> int:
        roots = conn.execute(
            "SELECT id FROM nodes WHERE node_type = 'root' ORDER BY path"
        ).fetchall()
        conn.execute("UPDATE nodes SET root_order = NULL WHERE node_type != 'root' OR node_type IS NULL")
        for order, (rid,) in enumerate(roots):
            conn.execute("UPDATE nodes SET root_order = ? WHERE id = ?", (order, rid))
        return len(roots)


# ====================================================================== MAIN AUTOMATED PROCESS

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


def process_single_zip(zip_path: Path, backend_dir: Path, db_warehouse: Path, 
                       static_warehouse: Path, current_dir: Path) -> Optional[Dict]:
    """Process a single zip file - designed for parallel execution."""
    with print_lock:
        print(f"\n{'='*70}")
        print(f"🔄 Processing: {zip_path.name}")
        print("=" * 70)
    
    # Extract zip and get the extracted folder path
    extract_dir = extract_zip(zip_path, current_dir)
    if extract_dir is None:
        return None
    
    # Find index.html in extracted folder (search recursively if needed)
    index_file = None
    for html_file in extract_dir.rglob("index.html"):
        index_file = html_file
        break
    
    if index_file is None:
        with print_lock:
            print(f"⚠️ No index.html found in {extract_dir}, skipping...")
        return None
    
    with print_lock:
        print(f"📄 Found index.html at: {index_file}")
    
    # Generate database name (remove "LEMON " prefix)
    db_name = zip_path.name.replace("LEMON ", "").replace(".zip", ".db")
    db_path = current_dir / db_name
    
    # Parse car info from database name
    brand, year, car_name = parse_car_info(db_name)
    with print_lock:
        print(f"🚗 Car info: {brand} {year} {car_name}")
    
    # Run HTML parser
    with print_lock:
        print(f"\n🔧 Parsing HTML for {db_name}...")
    
    parser = LogicalHTMLParser(
        html_dir=str(extract_dir),
        index_file=str(index_file),
        db_path=str(db_path)
    )
    parser.crawl()
    
    # Copy database to warehouse (rename without prefix/year)
    final_db_name = f"{car_name}.db"
    final_db_path = db_warehouse / final_db_name
    
    if db_path.exists():
        shutil.copy2(db_path, final_db_path)
        with print_lock:
            print(f"📁 Copied database to: {final_db_path}")
    else:
        with print_lock:
            print(f"⚠️ Database not found: {db_path}")
        return None
    
    # Copy images folder to static warehouse
    images_source = extract_dir / "images"
    if images_source.exists() and images_source.is_dir():
        images_dest = static_warehouse / car_name
        if images_dest.exists():
            shutil.rmtree(images_dest)
        shutil.copytree(images_source, images_dest)
        with print_lock:
            print(f"📁 Copied images to: {images_dest}")
    else:
        # Try searching for images folder recursively
        images_found = None
        for img_dir in extract_dir.rglob("images"):
            if img_dir.is_dir():
                images_found = img_dir
                break
        
        if images_found:
            images_dest = static_warehouse / car_name
            if images_dest.exists():
                shutil.rmtree(images_dest)
            shutil.copytree(images_found, images_dest)
            with print_lock:
                print(f"📁 Copied images from {images_found} to: {images_dest}")
        else:
            with print_lock:
                print(f"⚠️ No images folder found in {extract_dir}")
    
    # Optional: Cleanup extracted folder
    # shutil.rmtree(extract_dir)
    # with print_lock:
    #     print(f"🧹 Cleaned up: {extract_dir}")
    
    # Return car info for backend update
    return {
        'brand': brand,
        'year': year,
        'car_name': car_name,
        'db_address': f".\\Database_warehouse\\{final_db_name}"
    }


def process_all_zips(backend_path: str, max_workers: int = None):
    """Main function to process all LEMON zip files in parallel."""
    backend_dir = Path(backend_path).resolve()
    current_dir = Path.cwd()
    
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
    
    print("=" * 70)
    print("🚀 Starting Automated HTML Parser (Parallel)")
    print(f"📁 Backend directory: {backend_dir}")
    print(f"💾 Backend database: {db_backend}")
    print(f"📂 Database warehouse: {db_warehouse}")
    print(f"📂 Static warehouse: {static_warehouse}")
    print(f"⚡ Max workers: {max_workers}")
    print("=" * 70)
    
    # Find all LEMON zip files
    zip_files = list(current_dir.glob("LEMON *.zip"))
    
    if max_workers is None:
        max_workers = len(zip_files)

    if not zip_files:
        print("❌ No LEMON *.zip files found in current directory.")
        print(f"   Current directory: {current_dir}")
        sys.exit(1)
    
    print(f"\n📦 Found {len(zip_files)} zip file(s):")
    for zf in zip_files:
        print(f"   - {zf.name}")
    
    print(f"\n⚡ Processing {len(zip_files)} zip files with {max_workers} parallel workers...")
    
    # Process zips in parallel
    processed_cars = []
    failed_zips = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_zip = {
            executor.submit(process_single_zip, zip_path, backend_dir, db_warehouse, 
                          static_warehouse, current_dir): zip_path
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
                    failed_zips.append(zip_path.name)
                    with print_lock:
                        print(f"❌ Failed: {zip_path.name}")
            except Exception as e:
                failed_zips.append(zip_path.name)
                with print_lock:
                    print(f"❌ Error processing {zip_path.name}: {e}")
    
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
        description="Automated HTML parser for LEMON car data (parallel processing)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
USAGE:
  python htmlparser_logical.py "path/to/backend_folder"
  python htmlparser_logical.py "path/to/backend_folder" --workers 8

This will:
  1. Extract all LEMON *.zip files in the current directory (parallel)
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
    
    args = parser.parse_args()
    
    process_all_zips(args.backend_folder, args.workers)


if __name__ == "__main__":
    main()