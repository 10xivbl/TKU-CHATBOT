"""Recrawl scheduler for the three sections in sources.json.

  python scheduler.py --initial     first run: crawl EVERY URL in base, weekly
                                    and semi_annually, then write a FULL JSON
                                    export (this is the file to hand to the indexer)
  python scheduler.py               scheduled run: crawl only URLs that are due,
                                    then write an incremental export (changes only)
  python scheduler.py --dry-run     show what would be crawled, do nothing

Options: --only weekly,base   limit to some sections
         --no-export               skip the export step
         --out PATH                export file path

Intervals (days) live in tku/config.py: weekly 7, base 30, semi_annually 182.
Run it once a day from Windows Task Scheduler / cron; it only crawls what is due,
so a missed day simply catches up on the next run.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from tku.config import (  # noqa: E402
    SCHEDULED_SECTIONS, SECTION_INTERVAL_DAYS, load_sources, url_plan,
)
from tku.store import Store  # noqa: E402

# Don't retry a URL that was attempted less than this long ago (failed pages
# are retried on the next daily run instead of being hammered).
RETRY_COOLDOWN = timedelta(hours=20)


def parse(ts):
    return datetime.fromisoformat(ts) if ts else None


def find_due(plan, info, now):
    due = []
    for url, (section, _label) in plan.items():
        last_checked, last_attempt = info.get(url, (None, None))
        interval = timedelta(days=SECTION_INTERVAL_DAYS[section])
        lc, la = parse(last_checked), parse(last_attempt)
        if lc and now - lc < interval:
            continue
        if la and now - la < RETRY_COOLDOWN:
            continue
        due.append(url)
    return due


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--initial", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    sections = SCHEDULED_SECTIONS
    if args.only:
        sections = [s.strip() for s in args.only.split(",") if s.strip()]
        bad = [s for s in sections if s not in SECTION_INTERVAL_DAYS]
        if bad:
            sys.exit(f"Unknown section(s): {bad}. Choose from {SCHEDULED_SECTIONS}")

    plan = url_plan(load_sources(), sections)

    if args.initial:
        due = list(plan)
    else:
        store = Store()
        info = store.schedule_info()
        store.close()
        due = find_due(plan, info, datetime.now(timezone.utc))

    per_section = {s: sum(1 for u in due if plan[u][0] == s) for s in sections}
    print(f"{len(due)} of {len(plan)} URLs to crawl: {per_section}")
    if args.dry_run or not due:
        if not due:
            print("Nothing is due.")
        return

    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    urlfile = os.path.join("data", "due_urls.txt")
    with open(urlfile, "w", encoding="utf-8") as f:
        f.write("\n".join(due) + "\n")

    log = os.path.join("logs", f"crawl_{stamp}.log")
    cmd = [sys.executable, "-m", "scrapy", "crawl", "tkusite",
           "-a", f"urlfile={urlfile}",
           "-a", f"resultfile=data/crawl_results_{stamp}.jsonl",
           "-s", f"LOG_FILE={log}"]
    print(f"Crawling... (log: {log})")
    code = subprocess.run(cmd).returncode
    print(f"Crawl finished with exit code {code}.")

    if args.no_export:
        return
    exp = [sys.executable, "export.py"] + (["--full"] if args.initial else [])
    if args.only:
        exp += ["--section", ",".join(sections)]
    if args.out:
        exp += ["--out", args.out]
    subprocess.run(exp)


if __name__ == "__main__":
    main()
