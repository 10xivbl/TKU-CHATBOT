"""SQLite store: one current row per URL (upsert), plus change/failure tracking."""
import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

from tku.config import (
    ARTICLE_RECHECK_DAYS, ATTACHMENT_RECHECK_DAYS, FAILED_RETRY_DAYS, ROOT,
    STALE_RETRY_DAYS,
)

DB_PATH = os.path.join(ROOT, "seen.db")

# After this many consecutive failures a page is marked 'stale' and is left
# out of exports (and reported as removed if it was exported before).
STALE_AFTER = 3

COLUMNS = [
    ("hash", "TEXT"),
    ("final_url", "TEXT"),
    ("section", "TEXT"),
    ("label", "TEXT"),
    ("title", "TEXT"),
    ("heading", "TEXT"),
    ("lang", "TEXT"),
    ("type", "TEXT"),
    ("text", "TEXT"),
    ("first_seen", "TEXT"),
    ("last_changed", "TEXT"),
    ("last_checked", "TEXT"),    # last successful, accepted fetch
    ("last_attempt", "TEXT"),    # last fetch attempt, success or not
    ("fail_count", "INTEGER DEFAULT 0"),
    ("status", "TEXT DEFAULT 'active'"),
    ("exported_key", "TEXT"),    # what the last export contained
    ("kind", "TEXT"),            # page | article | attachment
    ("parent_url", "TEXT"),      # listing/article this one was found on
]


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path=DB_PATH):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, hash TEXT)")
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(pages)")}
        for name, typ in COLUMNS:
            if name not in have:
                self.db.execute(f"ALTER TABLE pages ADD COLUMN {name} {typ}")
        self.db.commit()
        self.counts = Counter()

    def close(self):
        self.db.commit()
        self.db.close()

    def get(self, url):
        return self.db.execute("SELECT * FROM pages WHERE url=?", (url,)).fetchone()

    def save_page(self, item):
        """Insert a new page or replace a changed one. Returns 'new' or 'changed'."""
        t = now()
        row = self.get(item["url"])
        kind = "new" if (row is None or row["text"] is None) else "changed"
        self.db.execute(
            """INSERT INTO pages (url, hash, final_url, section, label, title, heading,
                   lang, type, text, first_seen, last_changed, last_checked,
                   last_attempt, fail_count, status, kind, parent_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'active',?,?)
               ON CONFLICT(url) DO UPDATE SET
                   hash=excluded.hash, final_url=excluded.final_url,
                   section=COALESCE(excluded.section, pages.section),
                   label=COALESCE(excluded.label, pages.label),
                   kind=COALESCE(excluded.kind, pages.kind),
                   parent_url=COALESCE(excluded.parent_url, pages.parent_url),
                   title=excluded.title, heading=excluded.heading,
                   lang=excluded.lang, type=excluded.type, text=excluded.text,
                   first_seen=COALESCE(pages.first_seen, excluded.first_seen),
                   last_changed=excluded.last_changed,
                   last_checked=excluded.last_checked,
                   last_attempt=excluded.last_attempt,
                   fail_count=0, status='active'""",
            (item["url"], item["hash"], item.get("final_url"), item.get("section"),
             item.get("label"), item.get("title"), item.get("heading"),
             item.get("lang"), item.get("type"), item["text"], t, t, t, t,
             item.get("kind") or "page", item.get("parent_url")),
        )
        self.db.commit()
        self.counts[kind] += 1
        return kind

    def touch_unchanged(self, item):
        t = now()
        self.db.execute(
            """UPDATE pages SET last_checked=?, last_attempt=?, fail_count=0,
                   status='active', final_url=?, section=COALESCE(?, section),
                   label=COALESCE(?, label), title=COALESCE(?, title) WHERE url=?""",
            (t, t, item.get("final_url"), item.get("section"), item.get("label"),
             item.get("title"), item["url"]),
        )
        self.db.commit()
        self.counts["unchanged"] += 1

    def record_failure(self, url, section=None, label=None, kind=None, parent_url=None):
        t = now()
        self.db.execute(
            """INSERT INTO pages (url, section, label, kind, parent_url, last_attempt,
                                  fail_count, status)
               VALUES (?,?,?,?,?,?,1,'active')
               ON CONFLICT(url) DO UPDATE SET
                   last_attempt=excluded.last_attempt,
                   fail_count=COALESCE(pages.fail_count, 0) + 1,
                   section=COALESCE(excluded.section, pages.section),
                   label=COALESCE(excluded.label, pages.label),
                   kind=COALESCE(excluded.kind, pages.kind),
                   parent_url=COALESCE(excluded.parent_url, pages.parent_url)""",
            (url, section, label, kind, parent_url, t),
        )
        self.db.execute(
            "UPDATE pages SET status='stale' WHERE url=? AND fail_count>=?",
            (url, STALE_AFTER),
        )
        self.db.commit()
        self.counts["failed"] += 1

    def should_fetch(self, url, kind):
        """Should a discovered article/attachment be requested this run?"""
        row = self.get(url)
        if row is None:
            return True
        n = datetime.now(timezone.utc)

        def age(ts):
            return n - datetime.fromisoformat(ts) if ts else None

        if row["text"]:
            days = ATTACHMENT_RECHECK_DAYS if kind == "attachment" else ARTICLE_RECHECK_DAYS
            a = age(row["last_checked"])
            return a is None or a >= timedelta(days=days)
        # no text: an earlier attempt failed or was rejected
        wait = STALE_RETRY_DAYS if (row["fail_count"] or 0) >= STALE_AFTER else FAILED_RETRY_DAYS
        a = age(row["last_attempt"])
        return a is None or a >= timedelta(days=wait)

    def schedule_info(self):
        """{url: (last_checked, last_attempt)} for the scheduler."""
        rows = self.db.execute("SELECT url, last_checked, last_attempt FROM pages")
        return {r["url"]: (r["last_checked"], r["last_attempt"]) for r in rows}
