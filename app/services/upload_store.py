from __future__ import annotations

import secrets
from typing import Dict, Optional, Tuple

_UPLOAD_PREFIX = "upload://"
_UPLOADS: Dict[str, Tuple[bytes, str]] = {}


def store_upload(content: bytes, filename: str) -> str:
    token = secrets.token_urlsafe(16)
    _UPLOADS[token] = (content, filename)
    return f"{_UPLOAD_PREFIX}{token}"


def pop_upload(upload_url: str) -> Optional[Tuple[bytes, str]]:
    if not upload_url.startswith(_UPLOAD_PREFIX):
        return None
    token = upload_url[len(_UPLOAD_PREFIX):]
    return _UPLOADS.pop(token, None)


def is_upload_url(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(_UPLOAD_PREFIX)
