# Quick look at what is in seen.db
import sqlite3, collections
db = sqlite3.connect("seen.db")
db.row_factory = sqlite3.Row
rows = db.execute("SELECT * FROM pages").fetchall()
print(len(rows), "URLs tracked")
print("by status :", collections.Counter(r["status"] for r in rows))
print("by section:", collections.Counter(r["section"] for r in rows))
print("by kind   :", collections.Counter(r["kind"] or "page" for r in rows))
print("by type   :", collections.Counter(r["type"] for r in rows if r["text"]))
print("by lang   :", collections.Counter(r["lang"] for r in rows if r["text"]))
print("\nFailing / stale:")
for r in rows:
    if r["fail_count"]:
        print(f'  {r["fail_count"]}x {r["status"]:6} {r["label"] or ""} {r["url"]}')
print("\nShortest pages:")
for r in sorted((r for r in rows if r["text"]), key=lambda r: len(r["text"]))[:15]:
    print(f'  {len(r["text"]):6} {(r["title"] or "")[:40]} {r["url"]}')
