"""Export crawled pages from seen.db for the RAG indexer.

  python export.py --full       every active page (use for the initial hand-off)
  python export.py              only pages new/changed since the last export
  python export.py --full --section weekly,base   limit to sections

Default output is JSONL, one page per line, in the same format as the old
data/pages.jsonl:
  url, site, depth, type, title, heading, lang, text, hash, crawled_at
plus extra fields appended at the end: id, final_url, section, label, kind
(page | article | attachment), parent_url (the page an article or attachment
was found on), first_seen, last_changed, last_checked.

  --strict-old   write ONLY the ten old fields (no extras)
  --json         one JSON file {"generated_at","mode","count","pages","removed"}
  --out PATH     output path (default data/export/tku_<mode>_<timestamp>.jsonl)
  --keep-duplicates  keep pages whose text is identical to another page (default: only
                 one copy is exported; see below)
  --no-mark      don't mark pages as exported

Duplicates: departments often cross-post the same notice and attach their own copy of
the same file, so many pages have identical text. By default one copy is exported (the
earliest seen; ties go to the shortest URL) with an "also_at" list of the other URLs.
In an incremental export, a copy exported earlier that turns out to be a duplicate is
listed in the removed file.

Incremental exports mark pages as delivered, so the next one only holds what
changed after it. Pages that went stale since the last export are listed, one
URL per line, in a separate tku_removed_<timestamp>.txt next to the export.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from tku.store import Store  # noqa: E402


def export_key(row):
    # label/section are part of the key so a relabel also triggers a re-export
    return f"{row['hash']}|{row['label'] or ''}|{row['section'] or ''}"


def old_record(r):
    """The old pages.jsonl format, same field names and order."""
    return {
        "url": r["url"],
        "site": urlsplit(r["final_url"] or r["url"]).hostname or "",
        "depth": 0,
        "type": r["type"],
        "title": r["title"],
        "heading": r["heading"],
        "lang": r["lang"],
        "text": r["text"],
        "hash": r["hash"],
        "crawled_at": r["last_changed"],
    }


def full_record(r):
    p = old_record(r)
    p.update({
        "id": hashlib.sha1(r["url"].encode()).hexdigest()[:16],
        "final_url": r["final_url"],
        "section": r["section"],
        "label": r["label"],
        "kind": r["kind"] or "page",
        "parent_url": r["parent_url"],
        "first_seen": r["first_seen"],
        "last_changed": r["last_changed"],
        "last_checked": r["last_checked"],
    })
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--section")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict-old", action="store_true")
    ap.add_argument("--keep-duplicates", action="store_true")
    ap.add_argument("--no-mark", action="store_true")
    args = ap.parse_args()

    store = Store()
    rows = store.db.execute(
        "SELECT * FROM pages WHERE status='active' AND text IS NOT NULL AND text != ''"
        " ORDER BY section, label, url").fetchall()

    # Identical text under several URLs: keep one copy, remember the others.
    duplicates, also_at = [], {}
    if not args.keep_duplicates:
        groups = {}
        for r in rows:
            groups.setdefault(r["hash"], []).append(r)
        keep_rows = []
        for group in groups.values():
            group.sort(key=lambda r: (r["first_seen"] or "", len(r["url"]), r["url"]))
            keep_rows.append(group[0])
            duplicates.extend(group[1:])
            if len(group) > 1:
                also_at[group[0]["url"]] = [r["url"] for r in group[1:]]
        rows = sorted(keep_rows, key=lambda r: (r["section"] or "", r["label"] or "", r["url"]))

    if args.section:
        wanted = {s.strip() for s in args.section.split(",")}
        rows = [r for r in rows if r["section"] in wanted]
    if not args.full:
        rows = [r for r in rows if r["exported_key"] != export_key(r)]

    removed = []
    if not args.full:
        removed = [r["url"] for r in store.db.execute(
            "SELECT url FROM pages WHERE status='stale' AND exported_key IS NOT NULL")]
        # a copy exported earlier that is now known to be a duplicate
        removed += [r["url"] for r in duplicates if r["exported_key"] is not None]

    pages = []
    for r in rows:
        p = (old_record if args.strict_old else full_record)(r)
        if not args.strict_old:
            p["also_at"] = also_at.get(r["url"], [])
        pages.append(p)

    mode = "full" if args.full else "changed"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "json" if args.json else "jsonl"
    out = args.out or os.path.join("data", "export", f"tku_{mode}_{stamp}.{ext}")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        if args.json:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                       "mode": mode, "count": len(pages), "pages": pages,
                       "removed": removed}, f, ensure_ascii=False, indent=1)
        else:
            for p in pages:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    removed_file = None
    if removed and not args.json:
        removed_file = os.path.join(os.path.dirname(out) or ".",
                                    f"tku_removed_{stamp}.txt")
        with open(removed_file, "w", encoding="utf-8") as f:
            f.write("\n".join(removed) + "\n")

    if not args.no_mark:
        for r in rows:
            store.db.execute("UPDATE pages SET exported_key=? WHERE url=?",
                             (export_key(r), r["url"]))
        stale_clear = "status='stale'" if args.full else \
            "status='stale' AND exported_key IS NOT NULL"
        store.db.execute(f"UPDATE pages SET exported_key=NULL WHERE {stale_clear}")
        for r in duplicates:                      # duplicates are not delivered
            store.db.execute("UPDATE pages SET exported_key=NULL WHERE url=?", (r["url"],))
        store.db.commit()
    store.close()
    msg = f"Exported {len(pages)} pages ({mode}) -> {out}"
    if duplicates:
        msg += f"; {len(duplicates)} duplicate pages skipped"
    if removed:
        msg += f"; {len(removed)} removed -> {removed_file or 'in the json'}"
    print(msg)


if __name__ == "__main__":
    main()
