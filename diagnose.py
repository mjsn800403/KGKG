#!/usr/bin/env python3
"""
Diagnose why a page that SHOULD be intermediate is still labeled end_path.

Usage:
    python diagnose.py path/to/output.db "Labor Times"

It walks the promotion chain and tells you exactly which link is broken:
  (1) Is the suspect page row even in the DB?  -> if not, crawl never reached it
  (2) Was its child page discovered & inserted? -> if not, body-link scan didn't run
  (3) Does child.parent_id == suspect.id ?      -> if not, breadcrumb strings diverge
  (4) Did reconciliation run / promote it?       -> compares to what it SHOULD be
"""
import sqlite3, sys, hashlib

def h(p: str) -> str:
    return hashlib.sha1(p.encode("utf-8")).hexdigest()

db = sys.argv[1]
needle = sys.argv[2] if len(sys.argv) > 2 else "Labor Times"

con = sqlite3.connect(db)
con.row_factory = sqlite3.Row

# Locate the suspect page (a real page row => file_type IS NOT NULL)
cands = con.execute(
    "SELECT * FROM nodes WHERE file_type IS NOT NULL AND (path LIKE ? OR title LIKE ?) "
    "ORDER BY length(path) LIMIT 10",
    (f"%{needle}%", f"%{needle}%"),
).fetchall()

if not cands:
    print(f"[1] ✗ No page row matches {needle!r}. The crawl never reached/inserted it.")
    print("     -> Check that some page links to it, and that you ran the MODIFIED file.")
    sys.exit()

for s in cands:
    print("=" * 72)
    print(f"SUSPECT: {s['path']}")
    print(f"  id={s['id'][:12]}  file_type={s['file_type']}  node_type={s['node_type']}  "
          f"content={'yes' if s['content'] else '-'}")
    print(f"  recomputed sha1(path)={h(s['path'])[:12]}  "
          f"{'(matches id)' if h(s['path'])==s['id'] else '✗ DOES NOT MATCH id'}")

    kids = con.execute(
        "SELECT path, file_type, parent_id FROM nodes WHERE parent_id = ? ORDER BY path",
        (s["id"],),
    ).fetchall()
    page_kids = [k for k in kids if k["file_type"] is not None]
    print(f"  children rows: {len(kids)}   (real-page children: {len(page_kids)})")

    if not kids:
        print("  [2] ✗ No children point at this row.")
        print("      Either the body-link scan didn't queue the child (old code?),")
        print("      OR the child landed under a DIFFERENT parent_id (string drift).")
        # Try to find the child by title to expose string drift
        near = con.execute(
            "SELECT path, parent_id FROM nodes WHERE path LIKE ? LIMIT 5",
            (s["path"] + "/%",),
        ).fetchall()
        for n in near:
            ok = "OK" if n["parent_id"] == s["id"] else "✗ parent_id differs"
            print(f"      under-path child: {n['path']!r}  parent_id={n['parent_id'][:12]} [{ok}]")
    else:
        for k in page_kids[:5]:
            print(f"      -> child page: {k['path']}  (file_type={k['file_type']})")

    should_be = "intermediate_path" if page_kids else "end_path (genuinely a leaf)"
    print(f"  VERDICT: should be {should_be}; is {s['file_type']}")
    if page_kids and s["file_type"] == "end_path":
        print("  [4] ✗ Has real-page children but still end_path "
              "=> _reconcile_file_types() did NOT run (or ran on a different db).")