import json
from collections import Counter, defaultdict
from urllib.parse import urlsplit
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "pages.jsonl"

host_counts = Counter()
host_chars = Counter()
host_types = defaultdict(Counter)

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    for line in f:
        try:
            page = json.loads(line)
        except json.JSONDecodeError:
            continue

        host = (urlsplit(page.get("url", "")).hostname or "").lower()

        if not host:
            continue

        text = page.get("text", "") or ""

        host_counts[host] += 1
        host_chars[host] += len(text)
        host_types[host][page.get("type", "unknown")] += 1

print(f"Total hosts: {len(host_counts)}")
print(f"Total pages: {sum(host_counts.values())}")

print("\n========== HOST BREAKDOWN ==========")

for host, count in host_counts.most_common():
    chars = host_chars[host]
    types = dict(host_types[host])

    print(
        f"{host:40} "
        f"{count:6} pages "
        f"{chars / 1000:10.1f}k chars "
        f"{types}"
    )
