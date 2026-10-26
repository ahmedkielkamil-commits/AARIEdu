"""
PDF lesson documents: MinIO storage, PyMuPDF extraction, and TTS-ready text.

Upload: admin flow mirroring the video upload route; PDFs live in the shared
MinIO bucket under their own key prefix.
Extraction: PyMuPDF renders each page to HTML. Embedded images are lifted out
to MinIO and referenced by presigned URL, so nothing ships as inline base64.
Playback: the image-free text is chunked so the TTS provider never receives a
single request longer than it can synthesize.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import tempfile
import uuid
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

import dcqueries as dq
import miniIO
import redis_conn as redis_jobs

logger = logging.getLogger(__name__)

PDF_KEY_PREFIX = os.getenv("MINIO_PDF_PREFIX", "documents/dc")
CACHE_KEY_PREFIX = "dc:pdfdoc:"
CACHE_TTL_SECONDS = int(os.getenv("PDF_CACHE_TTL_SECONDS", str(86400 * 7)))
PRESIGNED_EXPIRY_SECONDS = int(os.getenv("MINIO_PRESIGNED_EXPIRY", "3600"))
TTS_CHUNK_MAX_CHARS = int(os.getenv("TTS_CHUNK_MAX_CHARS", "2800"))
ALLOWED_PDF_EXTENSIONS = frozenset({"pdf"})

# Placeholder written into cached HTML in place of an image src. Presigned URLs
# expire, so they are re-signed on every read instead of being cached.
_IMG_TOKEN_PREFIX = "@@AARI_IMG:"
_IMG_TOKEN_SUFFIX = "@@"

_DATA_URI_SRC_RE = re.compile(r'src="(?P<uri>data:image/[^"]*)"', re.IGNORECASE)
_IMG_TOKEN_RE = re.compile(re.escape(_IMG_TOKEN_PREFIX) + r"(?P<key>[^@]+)" + re.escape(_IMG_TOKEN_SUFFIX))
_BODY_RE = re.compile(r"<body[^>]*>(?P<body>.*)</body>", re.DOTALL | re.IGNORECASE)
_PAGE_DIV_RE = re.compile(r'<div\s+id="page\d+"', re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# Lesson PDFs wrap code in a matching pair of this marker. TTS must skip
# the enclosed block (and the markers themselves); the viewer still shows it.
_CODE_SNIPPET_BLOCK_RE = re.compile(
    r"\[Code\s+Snippet\].*?\[Code\s+Snippet\]",
    re.IGNORECASE | re.DOTALL,
)
_CODE_SNIPPET_OPEN_RE = re.compile(r"\[Code\s+Snippet\]", re.IGNORECASE)


def _document_tmp_dir() -> Path:
    configured = os.getenv("DOCUMENT_TMP_DIR")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "aari-documents"


TMP_DIR = _document_tmp_dir()


class DocumentError(RuntimeError):
    """Raised when a lesson PDF cannot be stored or extracted."""


def _import_fitz():
    """Return the PyMuPDF module (``fitz`` is the deprecated alias for ``pymupdf``)."""
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        pass
    try:
        import fitz

        return fitz
    except ImportError as exc:  # pragma: no cover - depends on local install
        raise DocumentError(
            "PyMuPDF is not installed. Run: pip install PyMuPDF"
        ) from exc


def _cache_key(videoid: int) -> str:
    return f"{CACHE_KEY_PREFIX}{videoid}"


def _object_key_for_pdf(videoid: int) -> str:
    return f"{PDF_KEY_PREFIX}/{videoid}.pdf"


def _object_key_for_instructions(videoid: int) -> str:
    return f"{PDF_KEY_PREFIX}/instructions/{videoid}.pdf"


def _image_object_key(videoid: int, page_number: int, index: int, ext: str) -> str:
    return f"{PDF_KEY_PREFIX}/{videoid}/images/p{page_number:03d}-{index:02d}.{ext}"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def _save_upload_to_temp(upload: FileStorage) -> Path:
    if not upload or not upload.filename:
        raise DocumentError("No PDF file provided.")

    ext = Path(secure_filename(upload.filename)).suffix.lstrip(".").lower()
    if ext not in ALLOWED_PDF_EXTENSIONS:
        raise DocumentError(f"Unsupported format '.{ext}'. Allowed: pdf")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    dest = TMP_DIR / f"upload-{uuid.uuid4().hex}.pdf"
    upload.save(dest)
    return dest


def store_lesson_pdf(videoid: int, upload: FileStorage) -> dict[str, Any]:
    """
    Store an uploaded PDF in MinIO and record its key on the lesson row.

    Storage is fast enough to stay inline; only video needs the transcode queue.
    """
    video = dq.get_video(videoid)
    if not video:
        raise DocumentError(f"Video {videoid} not found.")

    source_path = _save_upload_to_temp(upload)
    object_key = _object_key_for_pdf(videoid)
    try:
        miniIO.upload_file(source_path, object_key, content_type="application/pdf")
        if not dq.update_video_pdfkey(videoid, object_key):
            raise DocumentError(f"Could not save PDF key for video {videoid}.")
        clear_cache(videoid)
        logger.info("Stored lesson PDF for video %s → %s", videoid, object_key)
    finally:
        try:
            if source_path.is_file():
                source_path.unlink()
        except OSError as err:
            logger.warning("Could not remove temp file %s: %s", source_path, err)

    return {"status": "stored", "videoid": videoid, "pdfkey": object_key}


def delete_lesson_pdf(videoid: int) -> dict[str, Any]:
    """Detach a PDF from a lesson so the video player takes over again."""
    video = dq.get_video(videoid)
    if not video:
        raise DocumentError(f"Video {videoid} not found.")
    dq.update_video_pdfkey(videoid, None)
    clear_cache(videoid)
    return {"status": "removed", "videoid": videoid}


def store_instructions_pdf(videoid: int, upload: FileStorage) -> dict[str, Any]:
    """Store the assignment instructions PDF shown after a lesson's video or document."""
    if not dq.get_video(videoid):
        raise DocumentError(f"Video {videoid} not found.")

    source_path = _save_upload_to_temp(upload)
    object_key = _object_key_for_instructions(videoid)
    try:
        miniIO.upload_file(source_path, object_key, content_type="application/pdf")
        if not dq.update_video_instructionskey(videoid, object_key):
            raise DocumentError(f"Could not save instructions PDF key for video {videoid}.")
        logger.info("Stored instructions PDF for video %s → %s", videoid, object_key)
    finally:
        try:
            if source_path.is_file():
                source_path.unlink()
        except OSError as err:
            logger.warning("Could not remove temp file %s: %s", source_path, err)

    return {"status": "stored", "videoid": videoid, "pdfkey": object_key}


def delete_instructions_pdf(videoid: int) -> dict[str, Any]:
    """Detach the assignment instructions PDF from a lesson."""
    if not dq.get_video(videoid):
        raise DocumentError(f"Video {videoid} not found.")
    dq.update_video_instructionskey(videoid, None)
    return {"status": "removed", "videoid": videoid}


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _store_inline_image(
    data_uri: str, videoid: int, page_number: int, index: int
) -> str | None:
    """Fallback: persist a base64 <img> payload that get_images() did not report."""
    header, _, payload = data_uri.partition(",")
    if not payload:
        return None
    ext = "png"
    match = re.match(r"data:image/(?P<ext>[a-z0-9.+-]+)", header, re.IGNORECASE)
    if match:
        ext = match.group("ext").lower()
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    key = _image_object_key(videoid, page_number, index, ext)
    miniIO.upload_bytes(raw, key, content_type=f"image/{ext}")
    return key


def _extract_page_images(doc, page, videoid: int, page_number: int) -> list[str]:
    """Upload every embedded image on a page to MinIO; return keys in page order."""
    keys: list[str] = []
    for index, info in enumerate(page.get_images(full=True)):
        xref = info[0]
        try:
            extracted = doc.extract_image(xref)
        except Exception as err:
            logger.warning(
                "Could not extract image xref %s on page %s: %s", xref, page_number, err
            )
            continue
        data = extracted.get("image")
        if not data:
            continue
        ext = (extracted.get("ext") or "png").lower()
        key = _image_object_key(videoid, page_number, index, ext)
        miniIO.upload_bytes(data, key, content_type=f"image/{ext}")
        keys.append(key)
    return keys


def _rewrite_image_sources(
    page_html: str, image_keys: list[str], videoid: int, page_number: int
) -> str:
    """Replace base64 <img> sources with MinIO placeholder tokens, in page order."""
    pending = list(image_keys)
    overflow_index = len(image_keys)

    def replace(match: re.Match[str]) -> str:
        nonlocal overflow_index
        if pending:
            key = pending.pop(0)
        else:
            key = _store_inline_image(
                match.group("uri"), videoid, page_number, overflow_index
            )
            overflow_index += 1
            if key is None:
                return match.group(0)
        return f'src="{_IMG_TOKEN_PREFIX}{key}{_IMG_TOKEN_SUFFIX}"'

    return _DATA_URI_SRC_RE.sub(replace, page_html)


def _rgb_to_hex(color) -> str:
    r, g, b = (max(0.0, min(1.0, c)) for c in color[:3])
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def _page_fill_rects(page) -> str:
    """
    Recreate filled shapes that PyMuPDF's HTML export drops.

    Code blocks in lesson PDFs sit on black rectangles so the syntax-highlight
    colors stay readable. Without these fills the viewer shows that text on
    the white page.
    """
    page_area = abs(page.rect.width * page.rect.height)
    parts: list[str] = []
    for drawing in page.get_drawings():
        fill = drawing.get("fill")
        rect = drawing.get("rect")
        if not fill or rect is None:
            continue
        if all(c >= 0.95 for c in fill[:3]):
            continue
        if abs(rect.width * rect.height) > page_area * 0.8:
            continue
        if abs(rect.width) < 1 or abs(rect.height) < 1:
            continue
        parts.append(
            '<div class="pdf-draw" style="'
            f"left:{rect.x0:.2f}pt;top:{rect.y0:.2f}pt;"
            f"width:{abs(rect.width):.2f}pt;height:{abs(rect.height):.2f}pt;"
            f'background:{_rgb_to_hex(fill)}"></div>'
        )
    return "".join(parts)


def _page_fragment(page_html: str, page_number: int, fill_html: str = "") -> str:
    """
    Return the body of a PyMuPDF page, tagged for the viewer stylesheet.

    PyMuPDF numbers every standalone page ``page0`` and puts its positioning
    rules in a <head> we drop, so the canvas gets a unique id and a class the
    app stylesheet can target.
    """
    match = _BODY_RE.search(page_html)
    body = (match.group("body") if match else page_html).strip()
    tagged = _PAGE_DIV_RE.sub(
        f'<div id="pdf-page-{page_number}" class="pdf-page-canvas"', body, count=1
    )
    if fill_html:
        tagged = re.sub(
            rf'(<div id="pdf-page-{page_number}" class="pdf-page-canvas"[^>]*>)',
            rf"\1{fill_html}",
            tagged,
            count=1,
        )
    return tagged


def _build_document(videoid: int, pdf_path: Path) -> dict[str, Any]:
    """Render every page to HTML with MinIO-backed images and image-free text."""
    fitz = _import_fitz()
    fragments: list[str] = []

    doc = fitz.open(pdf_path)
    try:
        for page_number, page in enumerate(doc, start=1):
            page_html = page.get_text("html")
            image_keys = _extract_page_images(doc, page, videoid, page_number)
            page_html = _rewrite_image_sources(
                page_html, image_keys, videoid, page_number
            )
            fragments.append(
                f'<section class="pdf-page" data-page="{page_number}">'
                f"{_page_fragment(page_html, page_number, _page_fill_rects(page))}"
                "</section>"
            )
    finally:
        doc.close()

    html = '<div class="pdf-document">' + "\n".join(fragments) + "</div>"
    return {
        "html": html,
        "text": html_to_plain_text(html),
        "page_count": len(fragments),
    }


def _resolve_image_tokens(html: str) -> str:
    """Swap cached placeholders for freshly signed MinIO URLs."""

    def replace(match: re.Match[str]) -> str:
        key = match.group("key")
        try:
            url = miniIO.presigned_get_url(
                key, expires_seconds=PRESIGNED_EXPIRY_SECONDS
            )
        except Exception as err:
            logger.warning("Could not sign image %s: %s", key, err)
            return ""
        return escape(url, quote=True)

    return _IMG_TOKEN_RE.sub(replace, html)


def clear_cache(videoid: int) -> None:
    try:
        redis_jobs.get_redis_connection().delete(_cache_key(videoid))
    except Exception as err:
        logger.warning("Could not clear PDF cache for video %s: %s", videoid, err)


def _read_cache(videoid: int) -> dict[str, Any] | None:
    try:
        raw = redis_jobs.get_redis_connection().get(_cache_key(videoid))
    except Exception as err:
        logger.warning("PDF cache unavailable for video %s: %s", videoid, err)
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _write_cache(videoid: int, payload: dict[str, Any]) -> None:
    try:
        redis_jobs.get_redis_connection().set(
            _cache_key(videoid), json.dumps(payload), ex=CACHE_TTL_SECONDS
        )
    except Exception as err:
        logger.warning("Could not cache PDF for video %s: %s", videoid, err)


def get_document(videoid: int, *, refresh: bool = False) -> dict[str, Any]:
    """
    Return the extracted document for a lesson PDF.

    HTML carries MinIO image URLs; ``text`` and ``chunks`` are image-free and
    safe to send to TTS.
    """
    video = dq.get_video(videoid)
    if not video:
        raise DocumentError(f"Video {videoid} not found.")

    pdfkey = video.get("pdfkey")
    if not pdfkey:
        raise DocumentError("This lesson has no PDF document.")

    cached = None if refresh else _read_cache(videoid)
    if cached is None:
        if not miniIO.object_exists(pdfkey):
            raise DocumentError("Stored PDF is missing from object storage.")

        TMP_DIR.mkdir(parents=True, exist_ok=True)
        local_path = TMP_DIR / f"extract-{videoid}-{uuid.uuid4().hex}.pdf"
        try:
            miniIO.download_file(pdfkey, local_path)
            cached = _build_document(videoid, local_path)
        finally:
            try:
                if local_path.is_file():
                    local_path.unlink()
            except OSError as err:
                logger.warning("Could not remove temp file %s: %s", local_path, err)
        _write_cache(videoid, cached)

    text = strip_code_snippets(cached.get("text", ""))
    chunks = chunk_text(text)
    return {
        "videoid": videoid,
        "html": _resolve_image_tokens(cached.get("html", "")),
        "text": text,
        "chunks": chunks,
        "chunk_count": len(chunks),
        "page_count": cached.get("page_count", 0),
    }


# ---------------------------------------------------------------------------
# TTS text
# ---------------------------------------------------------------------------


class _PlainTextExtractor(HTMLParser):
    """Collect readable text nodes in document order, dropping images entirely."""

    _SKIPPED = frozenset({"script", "style", "head", "title"})
    _BREAKING = frozenset(
        {
            "p", "div", "section", "article", "br", "li", "tr", "td", "th",
            "table", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIPPED:
            self._skip_depth += 1
        elif tag in self._BREAKING:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BREAKING:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def strip_code_snippets(text: str) -> str:
    """
    Drop blocks wrapped in a pair of ``[Code Snippet]`` markers.

    Those blocks stay in the HTML viewer. They must never be sent to TTS.
    An unmatched opener (missing closer) drops everything after it so a
    broken pair cannot leak source code into the spoken script.
    """
    if not text:
        return ""
    cleaned = _CODE_SNIPPET_BLOCK_RE.sub("", text)
    leftover = _CODE_SNIPPET_OPEN_RE.search(cleaned)
    if leftover:
        cleaned = cleaned[: leftover.start()]
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def html_to_plain_text(html: str) -> str:
    """
    Strip tags and images from extracted HTML, leaving readable text in order.

    This is the only form sent to TTS — images are display-only. Code
    wrapped in ``[Code Snippet]`` pairs is also removed from this text.
    """
    if not html:
        return ""
    parser = _PlainTextExtractor()
    parser.feed(html)
    parser.close()

    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in parser.text().split("\n")]
    text = "\n".join(line for line in lines if line)
    return strip_code_snippets(re.sub(r"\n{3,}", "\n\n", text))


def _split_oversized(block: str, max_chars: int) -> list[str]:
    """Split one paragraph on sentence boundaries, hard-cutting as a last resort."""
    if len(block) <= max_chars:
        return [block]

    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT_RE.split(block):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, max_chars: int = TTS_CHUNK_MAX_CHARS) -> list[str]:
    """
    Split text into TTS-sized chunks on paragraph, then sentence, boundaries.

    ElevenLabs caps characters per request, so long documents are
    synthesized as a sequence of requests and played back to back.
    """
    if not text or not text.strip():
        return []
    max_chars = max(200, max_chars)

    chunks: list[str] = []
    current = ""
    for block in (b.strip() for b in text.split("\n") if b.strip()):
        for piece in _split_oversized(block, max_chars):
            if not current:
                current = piece
            elif len(current) + 1 + len(piece) <= max_chars:
                current = f"{current}\n{piece}"
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def get_pdf_url(videoid: int) -> str | None:
    """Presigned URL for the raw PDF (download / fallback viewing)."""
    video = dq.get_video(videoid)
    if not video or not video.get("pdfkey"):
        return None
    pdfkey = video["pdfkey"]
    if not miniIO.object_exists(pdfkey):
        return None
    return miniIO.presigned_get_url(pdfkey, expires_seconds=PRESIGNED_EXPIRY_SECONDS)
