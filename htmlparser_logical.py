# htmlparser_logical.py
#
# Breadcrumb-driven, link-crawled parser. (Successor to htmlparser_claude_7.py.)
#
# WHAT CHANGED vs. the filesystem-mirror approach
# ------------------------------------------------
#   * DISCOVERY is logical, not on-disk. We start at ONE index.html (a specific
#     car model) and crawl outward by FOLLOWING STRUCTURAL <a href="pages/N.html">
#     links recursively. The folder layout on disk is NEVER used as a signal
#     (it may be messy); files are only LOCATED by basename so their bytes can
#     be read and parsed.
#   * IDENTITY is the BREADCRUMB logical path. The chain of <a class="breadcrumb-part">
#     gives every page its absolute path in the tree; parent = strip last segment.
#     The same node seen as a leaf-link in a parent page and as its own page
#     dedupe to ONE row by this path.
#   * file_type is decided ONLY from a file's own HTML context:
#         - no navigation children            -> 'end_path'  (+ store content)
#         - hosts its own first-degree children-> 'intermediate_path'
#         - the single provided index.html     -> 'root_path'
#   * node_type (root/folder/leaf) is the SAME page-local DOM rule as before.
#
# HOW DEPTH IS REACHED
# --------------------
#   Split-tree pages are deliberately cut at a depth, so deeper nodes are not
#   present in any one page. Depth is reached by (a) DOM recursion through the
#   <a name="…/"> folder anchors inside a page, and (b) opening each structural
#   <a href="pages/N.html"> leaf as a new page and continuing from ITS breadcrumb.
#   An explicit BFS queue + visited-set walks the whole model subtree.

import re
import sqlite3
import hashlib
from collections import deque
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from bs4 import BeautifulSoup

PARSER = "html5lib"  # MANDATORY: html.parser / lxml mis-nest the unclosed <li> tags.


class LogicalHTMLParser:
    def __init__(self, html_dir: str, index_file: str, db_path: str = "nodes.db"):
        # html_dir is searched ONLY to locate files by basename (layout-agnostic).
        self.html_dir = Path(html_dir).resolve()
        self.index_file = Path(index_file).resolve()
        self.db_path = db_path
        self.files_by_basename: Dict[str, Path] = {}
        self.model_root: str = ""        # escaped last-breadcrumb segment of index.html
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
                print(f"⚠️ duplicate basename '{p.name}' — keeping "
                      f"{self.files_by_basename[key]}, ignoring {p}")
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
        nested deeper and are intentionally never treated as navigation."""
        return main.find("ul", recursive=False) if main else None

    def _classify_file_type(self, main, is_index: bool) -> str:
        """FILE axis, decided purely from this file's own HTML context.

        Equivalent to the breadcrumb-name rule: a page is 'intermediate_path' iff
        its own breadcrumb-leaf is the FIRST-DEGREE parent of something — i.e. its
        nav <ul> directly lists a child (an <a name='…/'> folder, or a structural
        child-page <a href='pages/N.html'> with no cross-ref fragment). Otherwise
        'end_path'. The provided index.html is always 'root_path'."""
        if is_index:
            return "root_path"
        nav = self._nav_ul(main)
        if nav is None:
            return "end_path"
        for li in nav.find_all("li", recursive=False):
            a = li.find("a", recursive=False)
            if a is None:
                continue
            if a.get("name") is not None:
                return "intermediate_path"               # a hosted folder = first-degree child
            href = a.get("href")
            if not self._has_fragment(href) and self._is_followable(self._resolve_basename(href)):
                return "intermediate_path"               # a hosted child page = first-degree child
        return "end_path"                                # only cross-refs / no children

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
        file_type = self._classify_file_type(main, is_index)
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
                    print(f"  …{processed} pages, {total_nodes} node rows, {len(queue)} queued")
            except Exception as e:
                failed += 1
                print(f"❌ {fp}: {e}")

        conn.commit()
        roots_n = self._assign_root_order(conn)
        conn.commit()
        conn.execute("PRAGMA optimize;")
        conn.close()

        print("\n" + "=" * 70)
        print("📊 SUMMARY")
        print(f"✅ Pages processed : {processed}")
        print(f"❌ Failed          : {failed}")
        print(f"🧩 Node rows upserted (incl. dedup): {total_nodes}")
        print(f"🌱 Root nodes ordered: {roots_n}")
        print(f"💾 Database        : {self.db_path}")

    def _assign_root_order(self, conn: sqlite3.Connection) -> int:
        roots = conn.execute(
            "SELECT id FROM nodes WHERE node_type = 'root' ORDER BY path"
        ).fetchall()
        conn.execute("UPDATE nodes SET root_order = NULL WHERE node_type != 'root' OR node_type IS NULL")
        for order, (rid,) in enumerate(roots):
            conn.execute("UPDATE nodes SET root_order = ? WHERE id = ?", (order, rid))
        return len(roots)


# ====================================================================== READ
# Serve-side helpers — unchanged in spirit: bounded-depth fetch -> tree -> HTML.

def fetch_subtree(db_path: str, root_id: str, max_depth: int = 2) -> List[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        WITH RECURSIVE subtree(id, parent_id, title, node_type, file_type,
                               href, sort_order, depth_from_root, content) AS (
            SELECT id, parent_id, title, node_type, file_type, href, sort_order, 0, content
            FROM nodes WHERE id = ?
            UNION ALL
            SELECT n.id, n.parent_id, n.title, n.node_type, n.file_type, n.href,
                   n.sort_order, s.depth_from_root + 1, n.content
            FROM nodes n JOIN subtree s ON n.parent_id = s.id
            WHERE s.depth_from_root < ?
        )
        SELECT * FROM subtree ORDER BY depth_from_root, parent_id, sort_order;
    """, (root_id, max_depth)).fetchall()
    conn.close()
    return rows


def build_tree(rows: List[sqlite3.Row], root_id: str) -> Optional[Dict[str, Any]]:
    by_parent: Dict[Optional[str], List[sqlite3.Row]] = {}
    for r in rows:
        by_parent.setdefault(r["parent_id"], []).append(r)

    def attach(node: sqlite3.Row) -> Dict[str, Any]:
        kids = sorted(by_parent.get(node["id"], []), key=lambda x: x["sort_order"])
        return {
            "id": node["id"],
            "title": node["title"],
            "type": node["node_type"],
            "file_type": node["file_type"],
            "href": node["href"],
            "content": node["content"],
            "children": [attach(k) for k in kids],
        }

    root = next((r for r in rows if r["id"] == root_id), None)
    return attach(root) if root else None


def render_html(node: Optional[Dict[str, Any]]) -> str:
    if not node:
        return ""

    def li(n: Dict[str, Any]) -> str:
        kids = (f"<ul>{''.join(li(c) for c in n['children'])}</ul>"
                if n["children"] else "")
        if n.get("file_type") == "end_path":
            label = f'<a href="{n.get("href") or "#"}">{n["title"]}</a>'
            cls = ' class="li-end" data-has-content="true"' if n.get("content") else ' class="li-end"'
        elif n["type"] in ("folder", "root"):
            label = f'<a href="{n["href"]}">{n["title"]}</a>' if n["href"] else f'<a>{n["title"]}</a>'
            cls = ' class="li-folder"'
        else:
            label = f'<a href="{n.get("href") or "#"}">{n["title"]}</a>'
            cls = ' class="li-leaf"'
        return f"<li{cls}>{label}{kids}</li>"

    return f"<ul>{li(node)}</ul>"


def main():
    # html_dir  : a folder containing ALL the model's html (any layout).
    # index_file: the single index.html for the specific car model to build from.
    parser = LogicalHTMLParser(
        html_dir="2025 Toyota Corolla Cross Hybrid S",
        index_file="2025 Toyota Corolla Cross Hybrid S/index.html",
        db_path="nodes.db",
    )
    parser.crawl()
    print("\n✨ Done. Serve a page with: build_tree(fetch_subtree(db, root_id, depth), root_id)")


if __name__ == "__main__":
    main()
