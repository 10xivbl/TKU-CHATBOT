"""Usage: python crawl.py <mode> [group]

Plain fetch of the URLs in a sources.json group. NO link following (depth 0).
For scheduled recrawls use scheduler.py instead; this is for manual runs.

Modes:
  test        fetch up to 50 URLs
  full        fetch the whole group
  retry       retry URLs listed in data/failed_urls.txt

Groups: all (default = base + weekly + semi_annually), base, weekly,
        semi_annually. Several groups can be comma-separated.

Examples:
  python crawl.py test weekly
  python crawl.py full base
  python crawl.py retry
"""

import os
import subprocess
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

mode = sys.argv[1] if len(sys.argv) > 1 else ""
group = sys.argv[2] if len(sys.argv) > 2 else "all"

if mode not in {"test", "full", "retry"}:
    print(__doc__)
    raise SystemExit(1)

os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)

if mode == "retry":
    failed = "data/failed_urls.txt"
    if not os.path.exists(failed) or os.path.getsize(failed) == 0:
        print("No failed URLs to retry.")
        raise SystemExit(0)
    log = "logs/crawl_retry.log"
    resultfile = "data/crawl_results_retry.jsonl"
    cmd = [sys.executable, "-m", "scrapy", "crawl", "tkusite",
           "-a", f"urlfile={failed}", "-a", f"resultfile={resultfile}"]
else:
    tag = group.replace(",", "_")
    log = f"logs/crawl_{tag}.log"
    resultfile = f"data/crawl_results_{tag}.jsonl"
    cmd = [sys.executable, "-m", "scrapy", "crawl", "tkusite",
           "-a", f"group={group}", "-a", f"resultfile={resultfile}"]
    if mode == "test":
        cmd += ["-s", "CLOSESPIDER_PAGECOUNT=50"]

if os.path.exists(resultfile):
    os.remove(resultfile)
cmd += ["-s", f"LOG_FILE={log}"]

print(f"Mode: {mode}; group: {group}; log: {log}")
print(f"Watch log: Get-Content {log} -Tail 3 -Wait")

proc = subprocess.Popen(cmd)
while True:
    try:
        proc.wait()
        break
    except KeyboardInterrupt:
        print("Stopping cleanly; wait and do not press Ctrl+C again...")

print(f"Finished with exit code {proc.returncode}.")
print('Summary: Select-String "Store counts|finish_reason" ' + log)
raise SystemExit(proc.returncode or 0)
