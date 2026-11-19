import json
import os
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

import scrapy
from scrapy import Request

from tku.config import (
    MAX_ATTACHMENT_BYTES, MAX_LINKS_PER_PAGE, RESERVED_KEYS, SCHEDULED_SECTIONS,
    load_sources, max_hop, normalize_url, url_plan,
)
from tku.links import (
    article_candidates, doc_candidates, doc_type_of, extract_links, fetchable_doc,
    READABLE_EXT,
)
from tku.store import Store


class TkusiteSpider(scrapy.Spider):
    """Fetch the listed URLs and, for sections that allow it, follow links.

    Depth per section is set in tku/config.py (SECTION_MAX_HOP):
      hop 0  the URL listed in sources.json
      hop 1  article pages linked from a listing page          (kind "article")
      hop 2  documents linked from articles or listings        (kind "attachment")
    Sections not in SECTION_MAX_HOP (base, semi_annually) stay at hop 0.

    Arguments:
      group     "all" (= base + weekly + semi_annually), or comma-separated groups
      urlfile   text file with one URL per line; overrides group
      resultfile  JSONL log of per-URL success/failure
    """

    name = "tkusite"

    def __init__(self, group="all", urlfile=None,
                 resultfile="data/crawl_results.jsonl", *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = load_sources()
        approved = cfg["approved_hosts"]
        self.denied = [d.lower() for d in cfg.get("denied_hosts", [])]
        self.approved = [d.lower() for d in approved]

        self.meta_by_url = url_plan(cfg, SCHEDULED_SECTIONS)

        if urlfile:
            urls = []
            with open(urlfile, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(normalize_url(line.split("\t", 1)[0]))
        else:
            if group == "all":
                groups = list(SCHEDULED_SECTIONS)
            else:
                groups = [g.strip() for g in group.split(",") if g.strip()]
            unknown = [g for g in groups if g in RESERVED_KEYS or g not in cfg]
            if unknown:
                raise ValueError(f"Unknown group(s) in sources.json: {unknown}")
            plan = url_plan(cfg, groups)
            self.meta_by_url = {**plan, **self.meta_by_url}
            urls = list(plan)

        self.start_urls = []
        for url in dict.fromkeys(u for u in urls if u):
            if self._host_ok(url, self.approved):
                self.start_urls.append(url)
            else:
                print(f"SKIPPED (host not approved): {url}")

        self.seen = set(self.start_urls)     # never request the same URL twice per run
        self.allowed_domains = approved
        self.resultfile = resultfile
        self.failed = {}
        os.makedirs(os.path.dirname(self.resultfile) or ".", exist_ok=True)
        os.makedirs("data", exist_ok=True)
        self.failed_file = os.path.join("data", "failed_urls.txt")
        self.store = Store()

    # ---- helpers --------------------------------------------------------
    @staticmethod
    def _host_ok(url, domains):
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in domains)

    def _link_allowed(self, url):
        return (urlparse(url).scheme in ("http", "https")
                and self._host_ok(url, self.approved)
                and not self._host_ok(url, self.denied))

    def _write_result(self, url, status, reason=""):
        record = {"url": url, "status": status, "reason": str(reason)[:500],
                  "time": datetime.now(timezone.utc).isoformat()}
        with open(self.resultfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _fail(self, url, reason, section=None, label=None):
        self.failed[url] = str(reason)[:200]
        self.store.record_failure(url, section, label)
        self._write_result(url, "failed", reason)

    # ---- requests -------------------------------------------------------
    def _requests(self):
        for url in self.start_urls:
            yield Request(url, callback=self.parse_item, errback=self.request_error,
                          dont_filter=True,
                          meta={"source_url": url, "hop": 0, "kind": "page"})

    # Scrapy 2.13+ uses start(); older versions use start_requests().
    async def start(self):
        for request in self._requests():
            yield request

    def start_requests(self):
        yield from self._requests()

    def _children(self, links, kind, hop, parent, section, label):
        """Requests for discovered links (article pages or documents)."""
        for link in links[:MAX_LINKS_PER_PAGE]:
            url = normalize_url(link["url"])
            if not url or url in self.seen or not self._link_allowed(url):
                continue
            self.seen.add(url)
            if not self.store.should_fetch(url, kind):
                continue
            meta = {"source_url": url, "hop": hop, "kind": kind, "parent_url": parent,
                    "section": section, "label": label, "anchor": link["text"]}
            if kind == "attachment":
                meta["download_maxsize"] = MAX_ATTACHMENT_BYTES
                meta["download_timeout"] = 120
            yield Request(url, callback=self.parse_item, errback=self.request_error,
                          meta=meta)

    # ---- callbacks ------------------------------------------------------
    def request_error(self, failure):
        request = failure.request
        url = request.meta.get("source_url", request.url)
        section, label = self._meta_for(url, request.meta)
        self.logger.warning("Request failed: %s (%s)", url, failure.value)
        self._fail(url, failure.value, section, label)

    def _meta_for(self, url, meta):
        if meta.get("kind", "page") == "page":
            return self.meta_by_url.get(url, (None, None))
        return meta.get("section"), meta.get("label")

    def parse_item(self, response):
        meta = response.meta
        url = meta.get("source_url", response.url)
        hop = meta.get("hop", 0)
        kind = meta.get("kind", "page")
        section, label = self._meta_for(url, meta)
        self._write_result(url, "success")

        header = lambda name: response.headers.get(name, b"").decode("utf-8", errors="ignore")
        dtype = doc_type_of(header("Content-Type"), header("Content-Disposition"), response.url)

        base = {
            "url": url,                      # the URL as listed / discovered
            "final_url": response.url,       # after redirects
            "site": urlparse(response.url).hostname or "",
            "section": section, "label": label,
            "kind": kind, "parent_url": meta.get("parent_url"),
            "anchor": meta.get("anchor"),
        }

        if dtype in READABLE_EXT:
            yield {**base, "type": dtype, "body": response.body}
            return
        if dtype == "legacy":
            self._fail(url, "legacy Office format (.doc/.xls/.ppt) not supported", section, label)
            return
        if dtype != "html":
            self._fail(url, f"unsupported content type: {header('Content-Type')}", section, label)
            return
        if kind == "attachment":
            self._fail(url, "expected a document but got a web page", section, label)
            return

        limit = max_hop(section, url if kind == "page" else "")
        attachments, children = [], []
        if hop < limit:
            links = extract_links(response.text, response.url)
            docs = doc_candidates(links)[:MAX_LINKS_PER_PAGE]
            attachments = [{"text": d["text"], "url": d["url"]} for d in docs]
            if hop == 0:                       # listing page: follow its articles
                arts = article_candidates(links, response.url, exclude=docs)
                children += list(self._children(arts, "article", hop + 1, url, section, label))
            fetch = [d for d in docs if fetchable_doc(d)]
            children += list(self._children(fetch, "attachment", hop + 1, url, section, label))

        yield {**base, "type": "html", "html": response.text,
               "title": response.css("title::text").get(),
               "attachments": attachments}
        for req in children:
            yield req

    def closed(self, reason):
        with open(self.failed_file, "w", encoding="utf-8") as f:
            for url in sorted(self.failed):
                f.write(f"{url}\n")
        self.logger.info("Store counts: %s", dict(self.store.counts))
        self.store.close()
