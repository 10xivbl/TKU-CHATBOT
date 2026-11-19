"""Find article links and document links in a page (pure lxml, no Scrapy)."""
import re
from urllib.parse import parse_qs, unquote, urlsplit

from lxml import html as lxml_html

from tku.config import MIN_ANCHOR_CHARS

# Documents we can read. Legacy Office formats are listed in the article text
# but not downloaded.
READABLE_EXT = {"pdf", "docx", "xlsx", "pptx", "txt", "csv"}
LEGACY_EXT = {"doc", "xls", "ppt", "rtf", "odt", "ods", "odp"}
SKIP_EXT = {"jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "ico", "mp3", "mp4",
            "avi", "mov", "wmv", "zip", "rar", "7z", "gz", "css", "js", "xml", "json"}

CHROME_TAGS = {"nav", "header", "footer", "aside"}
CHROME_TOKENS = {"menu", "nav", "navbar", "navigation", "breadcrumb", "breadcrumbs",
                 "footer", "sidebar", "pagination", "pager", "paging"}
UI_TEXT = {"more", "read more", "更多", "更多消息", "查看更多", "瀏覽更多", "詳全文",
           "詳細內容", "詳情", "next", "previous", "prev", "下一頁", "上一頁", "首頁",
           "末頁", "最後一頁", "top", "回頂端", "english", "login", "登入", "rss",
           "print", "列印", "回上頁", "back"}
PAGING_PARAMS = {"page", "paged", "pageno", "pageindex", "pagenum", "pn", "pagesize"}
# A date next to a link marks it as a news row (2026-11-10, 2026/11/10, 2026年11月10日,
# 115-10-01, 16 Dec 2025, Dec 16, 2025).
DATE_RE = re.compile(
    r"(?<!\d)(?:(?:19|20)\d{2}|1[0-4]\d)\s?[-/.年]\s?\d{1,2}\s?[-/.月]\s?\d{1,2}(?!\d)"
    r"|\b\d{1,2}\s[A-Z][a-z]{2,8}\.?,?\s(?:19|20)\d{2}\b"
    r"|\b[A-Z][a-z]{2,8}\.?\s\d{1,2},?\s(?:19|20)\d{2}\b")
DOWNLOAD_HINT = re.compile(r"download|attach|fileupload|getfile|filedownload|file\.ashx|/files?/", re.I)


def _ext(path):
    m = re.search(r"\.([a-z0-9]{2,5})$", unquote(path).lower().rstrip("/"))
    return m.group(1) if m else ""


def _in_chrome(a):
    for anc in a.iterancestors():
        if anc.tag in CHROME_TAGS:
            return True
        if anc.tag in ("html", "body"):
            continue
        tokens = re.split(r"[\s_-]+", f"{anc.get('class', '')} {anc.get('id', '')}".lower())
        if CHROME_TOKENS.intersection(tokens):
            return True
    return False


def _has_date(a, text):
    """Is there a date in the link text or in the row (li/tr/div) around it?"""
    if DATE_RE.search(text):
        return True
    node = a
    for _ in range(3):
        node = node.getparent()
        if node is None or node.tag in ("body", "html", "ul", "ol", "table", "tbody", "thead"):
            break                          # a whole list/table is not one row
        row_text = " ".join(" ".join(node.itertext()).split())
        if len(row_text) > 400:            # too broad: a whole list, not one row
            break
        if DATE_RE.search(row_text):
            return True
    return False


def extract_links(html_text, base_url):
    """[{url, text, chrome}] for every http(s) link, in document order."""
    try:
        tree = lxml_html.fromstring(html_text)
        tree.make_links_absolute(base_url)
    except Exception:
        return []
    out = []
    for a in tree.iter("a"):
        href = (a.get("href") or "").strip()
        if not href.lower().startswith(("http://", "https://")):
            continue
        text = " ".join(a.text_content().split())
        title = " ".join((a.get("title") or "").split())
        if len(title) > len(text):
            text = title
        out.append({"url": href.split("#", 1)[0], "text": text,
                    "chrome": _in_chrome(a), "dated": _has_date(a, text)})
    return out


def is_doc_link(link):
    parts = urlsplit(link["url"])
    ext = _ext(parts.path)
    if ext in READABLE_EXT or ext in LEGACY_EXT:
        return True
    if ext in SKIP_EXT:
        return False
    text_ext = _ext(link["text"])
    if text_ext in READABLE_EXT or text_ext in LEGACY_EXT:
        return True
    return bool(DOWNLOAD_HINT.search(link["url"]))


def doc_candidates(links):
    """Non-menu document links, de-duplicated, in document order."""
    seen, out = set(), []
    for l in links:
        if l["chrome"] or not is_doc_link(l) or l["url"] in seen:
            continue
        seen.add(l["url"])
        out.append(l)
    return out


def fetchable_doc(link):
    """Legacy Office files are listed in the article text but not downloaded."""
    return _ext(urlsplit(link["url"]).path) not in LEGACY_EXT and \
        _ext(link["text"]) not in LEGACY_EXT


def article_candidates(links, page_url, exclude=()):
    """Links that look like news articles on a listing page."""
    page = urlsplit(page_url)
    skip = {l["url"] for l in exclude}
    seen, out = set(), []
    for l in links:
        url, text = l["url"], l["text"]
        if l["chrome"] or url in skip or url in seen or url == page_url:
            continue
        parts = urlsplit(url)
        if parts.path in ("", "/") and not parts.query:
            continue                                   # a site homepage
        if _ext(parts.path) in SKIP_EXT or is_doc_link(l):
            continue
        if len(text) < MIN_ANCHOR_CHARS or text.isdigit() or text.lower() in UI_TEXT:
            continue
        if PAGING_PARAMS.intersection(k.lower() for k in parse_qs(parts.query)):
            continue                                   # pagination
        if parts.netloc == page.netloc and parts.path == page.path and parts.query == page.query:
            continue
        seen.add(url)
        out.append(l)
    # News rows carry a date. Put them first so a menu that was not recognised as
    # one (and comes earlier in the page) cannot use up the per-page link cap.
    return sorted(out, key=lambda l: not l["dated"])


def doc_type_of(content_type, disposition, url):
    """'pdf'|'docx'|'xlsx'|'pptx'|'txt'|'csv'|'legacy'|'html'|None."""
    ct = (content_type or "").lower()
    cd = unquote(disposition or "").lower()
    m = re.search(r"filename\*?=(?:utf-8'')?\"?([^\";]+)", cd)
    ext = _ext(m.group(1)) if m else ""
    ext = ext or _ext(urlsplit(url).path)

    if "pdf" in ct:
        return "pdf"
    if "wordprocessingml" in ct:
        return "docx"
    if "spreadsheetml" in ct:
        return "xlsx"
    if "presentationml" in ct:
        return "pptx"
    if "msword" in ct or "ms-excel" in ct or "ms-powerpoint" in ct:
        return "legacy"
    if "html" in ct and ext not in READABLE_EXT | LEGACY_EXT:
        return "html"
    if ext in READABLE_EXT:
        return ext
    if ext in LEGACY_EXT:
        return "legacy"
    if ct.startswith("text/plain"):
        return "txt"
    if "csv" in ct:
        return "csv"
    if "html" in ct:
        return "html"
    return None
