import datetime
import hashlib
import io
import os
import re
from urllib.parse import unquote

import pymupdf
import trafilatura
from lxml import html as lxml_html
from scrapy.exceptions import DropItem

from tku.config import MAX_DOC_CHARS

# Repeated footer and menu lines.
BOILER = re.compile(
    r"^(Copyright©.*|No\.151, Yingzhuan.*|\+886-2-2621-5656|Last Updated.*|"
    r"Privacy & Security|Information Statement|Personal Information Declaration|:{3})\s*$", re.M)

# Page titles that mean "error page served with a normal 200 status".
SOFT_404 = ("Page not found", "404 Not Found", "File or directory not found", "找不到")

MIN_CHARS_HTML = 100
MIN_CHARS_PDF = 50

# Header/menu lines made only of nav words, e.g. "網站導覽 | 淡江大學首頁 | EN | 登入".
NAV_LINE = re.compile(
    r"^[\s|｜•·]*(?:(?:網站導覽|網站地圖|網站導航|淡江大學首頁|淡江大學|回首頁|首頁|"
    r"ENGLISH|English|EN|登入|Русский)[\s|｜•·]*)+$", re.M)

# Words that mark footer/contact lines. If an extraction is made ONLY of such
# lines, trafilatura picked the footer instead of the page body.
FOOTER_WORDS = re.compile(
    r"個資|隱私權|智財權|地址|電話|傳真|E-?MAIL|Copyright|Powered by|版權|聯絡窗口|"
    r"Privacy|Tel[:：.]|Fax", re.I)

BLOCK_TAGS = ("p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
              "table", "section", "article", "ul", "ol", "dd", "dt")


def footer_only(text):
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return False
    hits = sum(1 for l in lines if FOOTER_WORDS.search(l))
    return len(text) < 600 and hits / len(lines) >= 0.9


def plain_text(html):
    """Fallback extractor: all visible text of the page, one block per line."""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return ""
    for bad in tree.xpath("//head|//script|//style|//noscript|//iframe|//svg|//select|//button|//form"):
        bad.drop_tree()
    for el in tree.iter(*BLOCK_TAGS):
        el.tail = "\n" + (el.tail or "")
    for el in tree.iter("td", "th"):
        el.tail = " | " + (el.tail or "")
    lines = (" ".join(l.split()) for l in tree.text_content().splitlines())
    return "\n".join(l for l in lines if l)


def save_scanned_pdf(url: str, data: bytes) -> None:
    # Keep scanned PDFs (no text layer) so they can be OCR'd later
    os.makedirs("data/scanned_pdfs", exist_ok=True)
    name = hashlib.sha256(data).hexdigest()[:16]
    path = f"data/scanned_pdfs/{name}.pdf"
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
        with open("data/skipped_pdfs.txt", "a", encoding="utf-8") as f:
            f.write(f"{url}\t{path}\n")


DOC_TYPES = {"pdf", "docx", "xlsx", "pptx", "txt", "csv"}
GENERIC_ANCHORS = {"下載", "附件", "點擊下載", "點此下載", "檔案下載", "download", "attachment",
                   "click here", "here", "file", "pdf", "詳細內容", "more"}


def decode_text(data):
    for enc in ("utf-8-sig", "big5", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def extract_document(dtype, data):
    """Plain text of a downloaded document. Raises on unreadable files."""
    if dtype == "pdf":
        doc = pymupdf.open(stream=data, filetype="pdf")
        return "\n".join(p.get_text() for p in doc)
    if dtype == "docx":
        import docx                                   # python-docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                cells = []
                for c in row.cells:
                    if c.text.strip() and c.text.strip() not in cells:
                        cells.append(c.text.strip())
                parts.append(" | ".join(cells))
        return "\n".join(parts)
    if dtype == "xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets:
            parts.append(f"[{ws.title}]")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 2000:
                    break
                cells = [str(c).strip() for c in row if c not in (None, "")]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    if dtype == "pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        parts = []
        for n, slide in enumerate(prs.slides, 1):
            parts.append(f"[Slide {n}]")
            for shape in slide.shapes:
                if shape.has_text_frame:
                    parts.append(shape.text_frame.text)
                if getattr(shape, "has_table", False) and shape.has_table:
                    for row in shape.table.rows:
                        parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    return decode_text(data)                          # txt, csv


DATE_IN_TEXT = re.compile(r"(?:19|20)\d{2}\s?[-/.年]\s?\d{1,2}\s?[-/.月]\s?\d{1,2}日?|"
                          r"(?<!\d)1[0-4]\d\s?[-/.]\s?\d{1,2}\s?[-/.]\s?\d{1,2}(?!\d)")


def headline_title(title, anchor):
    """Article pages often have a <title> that is only the site or section name. If the
    list headline that linked to the article is missing from it, put it in front."""
    anchor = DATE_IN_TEXT.sub(" ", anchor or "")
    anchor = " ".join(anchor.replace("...", " ").replace("…", " ").split()).strip(" |-–")
    if len(anchor) < 6:
        return title
    key = anchor[:12]
    if key in title:
        return title
    return f"{anchor} – {title}" if title else anchor


def reject(spider, item, reason):
    """Count a rejected page as a failed attempt, then drop it."""
    spider.store.record_failure(item["url"], item.get("section"), item.get("label"),
                                item.get("kind"), item.get("parent_url"))
    raise DropItem(f"{reason}: {item['url']}")


class CleanPipeline:
    def process_item(self, item, spider):
        # Get the title and tidy its whitespace
        title = " ".join((item.get("title") or "").split())
        if any(s in title for s in SOFT_404):
            reject(spider, item, "soft 404")

        # Extract the text
        is_doc = item["type"] in DOC_TYPES
        is_pdf = item["type"] == "pdf"
        pdf_bytes = b""
        if is_doc:
            data = item.pop("body", b"")
            if not data:
                reject(spider, item, "document body missing")
            if is_pdf:
                pdf_bytes = data
            try:
                text = extract_document(item["type"], data)
            except Exception as e:                    # corrupt file or missing library
                reject(spider, item, f"cannot read {item['type']} ({type(e).__name__}: {e})")
            filename = unquote(item["final_url"].split("?")[0].rsplit("/", 1)[-1])
            anchor = " ".join((item.get("anchor") or "").split())
            # link texts like "下載" / "Download" say nothing; use the file name then
            title = filename if (len(anchor) < 4 or anchor.lower() in GENERIC_ANCHORS) else anchor
            if len(text) > MAX_DOC_CHARS:
                text = text[:MAX_DOC_CHARS] + "\n[truncated]"
        else:
            html = item.pop("html", "")
            text = trafilatura.extract(html, include_tables=True,
                                       favor_recall=True) or ""
            # On some templates trafilatura returns only the footer. Then fall
            # back to the page's plain visible text.
            if footer_only(text):
                alt = plain_text(html)
                if len(alt) > len(text):
                    text = alt

        # Clean first, then check the length of what is left
        text = re.sub(r"[ \t\u3000]+", " ", text)
        text = BOILER.sub("", text)
        text = NAV_LINE.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        # Documents/articles found by following links: list the attachments in the
        # text so they stay findable (and citable) even when a file can't be read.
        attachments = item.pop("attachments", None) or []
        if attachments:
            lines = [f"- {a['text'] or a['url'].rsplit('/', 1)[-1]}: {a['url']}"
                     for a in attachments]
            text = text + "\n\n附件 Attachments:\n" + "\n".join(lines)

        min_chars = (MIN_CHARS_PDF if is_doc
                     else 30 if item.get("kind") == "article" else MIN_CHARS_HTML)
        if len(text) < min_chars:
            if is_pdf:
                save_scanned_pdf(item["url"], pdf_bytes)
            reject(spider, item, "too short")

        if item.get("kind") == "article" and not is_doc:
            title = headline_title(title, item.get("anchor"))

        # Fill in the fields
        item["title"] = title
        item["heading"] = text.split("\n", 1)[0][:80]
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        item["lang"] = "zh" if cjk / len(text) > 0.1 else "en"
        item["text"] = text
        return item


class ChangePipeline:
    """Upsert into the store; unchanged pages only get their check time bumped."""

    def process_item(self, item, spider):
        # Ignore daily-changing dates so a date change alone doesn't count as an update
        norm = re.sub(r"Last Updated\s*:\s*\S+", "", item["text"])
        h = hashlib.sha256(norm.encode("utf-8")).hexdigest()

        row = spider.store.get(item["url"])
        # row["text"] is None for rows carried over from the old seen.db (hash only)
        if row and row["hash"] == h and row["text"] is not None:
            spider.store.touch_unchanged(item)
            raise DropItem("unchanged")

        item["hash"] = h
        item["crawled_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        spider.store.save_page(item)
        return item
