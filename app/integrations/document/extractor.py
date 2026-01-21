"""Document fetching and text extraction for PDF/HTML."""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from httpx import HTTPStatusError
from bs4 import BeautifulSoup
from pypdf import PdfReader

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/pdf",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

_SUPPORTED_CONTENT_KEYWORDS = ("pdf", "text/", "html", "xml")
_SUPPORTED_EXTENSIONS = {".pdf", ".html", ".htm", ".txt"}
_UNSUPPORTED_EXTENSIONS = {".avi", ".mp4", ".mov", ".mkv", ".zip", ".rar", ".gz"}


class DocumentExtractor:
    """Handles fetching and extracting text from documents."""
    
    @staticmethod
    async def fetch_content(url: str) -> Tuple[bytes, Optional[str]]:
        """Fetch raw content from a URL."""
        async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers=_BROWSER_HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").lower()
            return resp.content, content_type

    @staticmethod
    def pdf_bytes_to_text(data: bytes) -> str:
        """Extract text from PDF bytes."""
        reader = PdfReader(BytesIO(data))
        pages_text = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            pages_text.append(text)
        return "\n\n".join(pages_text)

    @staticmethod
    def html_bytes_to_text(data: bytes) -> str:
        """Extract text from HTML bytes."""
        soup = BeautifulSoup(data, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines)

    @staticmethod
    def _guess_extension(url: str) -> str:
        """Guess file extension from URL."""
        path = urlparse(url).path
        return Path(path).suffix.lower()

    @staticmethod
    def _is_supported_content(content_type: Optional[str], ext: str) -> bool:
        """Check if content type/extension is supported."""
        if ext in _UNSUPPORTED_EXTENSIONS:
            return False
        if ext in _SUPPORTED_EXTENSIONS:
            return True
        if content_type:
            ctype = content_type.lower()
            return any(token in ctype for token in _SUPPORTED_CONTENT_KEYWORDS)
        return False

    @staticmethod
    def looks_like_pdf_url(url: Optional[str]) -> bool:
        """Check if URL appears to point to a PDF."""
        if not url:
            return False
        parsed = urlparse(url)
        path = parsed.path.lower()
        query = parsed.query.lower()

        if path.endswith(".pdf"):
            return True
        if ".pdf" in path:
            return True
        if path.rstrip("/").endswith("pdf") or "/pdf/" in path:
            return True
        if any(token in query for token in ("pdf=", "pdf&", "blobtype=pdf", "format=pdf", "type=pdf")):
            return True
        return False

    async def fetch_and_extract_text(self, url: str) -> str:
        """Fetch a URL and extract text content."""
        normalized_url = url.strip()
        if not normalized_url:
            raise ValueError("URL is empty.")

        try:
            data, content_type = await self.fetch_content(normalized_url)
        except HTTPStatusError as exc:
            status = exc.response.status_code
            raise RuntimeError(
                f"Failed to fetch the provided URL (HTTP {status}). "
                "Access may require authentication, or the host may block automated requests."
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch the provided URL: {exc}") from exc

        ext = self._guess_extension(normalized_url)
        if not self._is_supported_content(content_type, ext):
            raise RuntimeError(
                "The provided URL does not look like a PDF or HTML document that can be processed. "
                "Please supply a direct link to an accessible PDF or HTML article."
            )

        if content_type and "pdf" in content_type:
            return self.pdf_bytes_to_text(data)
        if content_type and "octet-stream" in content_type and normalized_url.lower().endswith(".pdf"):
            return self.pdf_bytes_to_text(data)
        if ext == ".pdf":
            return self.pdf_bytes_to_text(data)
        
        # Otherwise treat as HTML/text
        try:
            return self.html_bytes_to_text(data)
        except Exception:
            try:
                return self.pdf_bytes_to_text(data)
            except Exception:
                return ""


# Convenience functions for backward compatibility
_extractor = DocumentExtractor()


async def fetch_and_extract_text(url: str) -> str:
    """Fetch a URL and extract text content."""
    return await _extractor.fetch_and_extract_text(url)


def pdf_bytes_to_text(data: bytes) -> str:
    """Extract text from PDF bytes."""
    return DocumentExtractor.pdf_bytes_to_text(data)
