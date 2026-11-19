# Pages and text size per host, from seen.db
import sqlite3, collections
from urllib.parse import urlsplit
db = sqlite3.connect("seen.db")
by = collections.defaultdict(lambda: [0, 0])
for url, text in db.execute("SELECT url, text FROM pages WHERE text IS NOT NULL"):
    h = urlsplit(url).hostname or ""
    by[h][0] += 1
    by[h][1] += len(text)
print(sum(v[0] for v in by.values()), "pages,", len(by), "hosts")
for h, (n, c) in sorted(by.items(), key=lambda x: -x[1][0]):
    print(f"{n:5d} pages {c//1000:6d}k chars  {h}")
