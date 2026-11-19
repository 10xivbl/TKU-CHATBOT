"""Shared config helpers: sources.json loading, sections and recrawl intervals."""
import json
import os
from urllib.parse import urlsplit, urlunsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_FILE = os.path.join(ROOT, "sources.json")

# Recrawl interval per section, in days. Ordered shortest first: when a URL is
# listed in more than one section, the shortest interval wins.
SECTION_INTERVAL_DAYS = {
    "weekly": 7,
    "semi_annually": 182,
}
SCHEDULED_SECTIONS = list(SECTION_INTERVAL_DAYS)
RESERVED_KEYS = {"approved_hosts", "denied_hosts"}


def load_sources():
    with open(SOURCES_FILE, encoding="utf-8") as f:
        return json.load(f)


def normalize_url(url):
    """Strip whitespace and the #fragment; keep path and query."""
    url = (url or "").strip()
    if not url:
        return ""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


def url_plan(cfg, groups):
    """Return {url: (section, label)} for the given groups, de-duplicated.

    A group may be a dict {url: label} (the new sections) or a plain list of
    URLs (old groups such as P0). Known sections are processed shortest
    interval first so the shortest interval wins on duplicates.
    """
    ordered = [g for g in SCHEDULED_SECTIONS if g in groups]
    ordered += [g for g in groups if g not in SCHEDULED_SECTIONS]
    plan = {}
    for g in ordered:
        value = cfg.get(g) or {}
        items = value.items() if isinstance(value, dict) else ((u, None) for u in value)
        for url, label in items:
            url = normalize_url(url)
            if url and url not in plan:
                plan[url] = (g, label)
    return plan


# ---------------------------------------------------------------- link following
# How deep to go from each listed URL, per section.
#   0 = fetch only the listed page itself
#   1 = also the article pages linked from it
#   2 = also the documents (PDF, Word, Excel...) linked from those articles
# Faculty (semi_annually) and base stay at 0.
SECTION_MAX_HOP = {"weekly": 2}

# Listed URLs matching any of these are never followed, even in a followed section
# (TAMX faculty lists, the calendar and the academic schedule live in "weekly").
NO_FOLLOW_PATTERNS = ("/Front/Faculty/", "Calendar.asp", "rtdoc_id")

MAX_LINKS_PER_PAGE = 10         # article links / document links taken per page
MIN_ANCHOR_CHARS = 6             # shorter link texts are treated as menu items

MAX_ARTICLE_AGE_DAYS = 90

# Already-stored articles/documents are not fetched again until this many days old.
ARTICLE_RECHECK_DAYS = 30
ATTACHMENT_RECHECK_DAYS = 365
# Pages that failed or yielded no text: wait before trying again.
FAILED_RETRY_DAYS = 7
STALE_RETRY_DAYS = 30

MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024
MAX_DOC_CHARS = 200_000          # longer documents are truncated


def max_hop(section, url=""):
    if any(p in (url or "") for p in NO_FOLLOW_PATTERNS):
        return 0
    return SECTION_MAX_HOP.get(section, 0)
