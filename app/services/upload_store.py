from __future__ import annotations

import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

_UPLOAD_PREFIX = "upload://"
_DEFAULT_TTL_SECONDS = 3600  # 1 hour

# Use a configurable upload dir; default to a persistent path if available, else temp
_UPLOAD_DIR: Optional[Path] = None


def _get_upload_dir() -> Path:
    global _UPLOAD_DIR
    if _UPLOAD_DIR is not None:
        return _UPLOAD_DIR

    configured = os.environ.get("UPLOAD_DIR", "").strip()
    if configured:
        p = Path(configured)
    else:
        # Try a project-relative persistent dir, fall back to system temp
        candidate = Path(os.environ.get("RENDER_DISK_MOUNT_PATH", "")) / "uploads" if os.environ.get("RENDER_DISK_MOUNT_PATH") else None
        if candidate and candidate.parent.exists():
            p = candidate
        else:
            p = Path(tempfile.gettempdir()) / "peptide_uploads"

    p.mkdir(parents=True, exist_ok=True)
    _UPLOAD_DIR = p
    return p


def store_upload(content: bytes, filename: str) -> str:
    token = secrets.token_urlsafe(16)
    upload_dir = _get_upload_dir()

    # Store content and metadata as two files: <token>.bin and <token>.meta
    bin_path = upload_dir / f"{token}.bin"
    meta_path = upload_dir / f"{token}.meta"

    bin_path.write_bytes(content)
    # meta: "<expires_at_unix>|<filename>"
    expires_at = int(time.time()) + _DEFAULT_TTL_SECONDS
    meta_path.write_text(f"{expires_at}|{filename}", encoding="utf-8")

    return f"{_UPLOAD_PREFIX}{token}"


def pop_upload(upload_url: str) -> Optional[Tuple[bytes, str]]:
    if not upload_url.startswith(_UPLOAD_PREFIX):
        return None
    token = upload_url[len(_UPLOAD_PREFIX):]
    upload_dir = _get_upload_dir()

    bin_path = upload_dir / f"{token}.bin"
    meta_path = upload_dir / f"{token}.meta"

    if not bin_path.exists() or not meta_path.exists():
        return None

    try:
        meta = meta_path.read_text(encoding="utf-8")
        expires_at_str, filename = meta.split("|", 1)
        if time.time() > int(expires_at_str):
            # Expired — clean up and return None
            _remove_upload_files(token, upload_dir)
            return None

        content = bin_path.read_bytes()
        _remove_upload_files(token, upload_dir)
        return (content, filename)
    except Exception:
        _remove_upload_files(token, upload_dir)
        return None


def _remove_upload_files(token: str, upload_dir: Path) -> None:
    for suffix in (".bin", ".meta"):
        p = upload_dir / f"{token}{suffix}"
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


def purge_expired_uploads() -> int:
    """Remove expired upload files. Returns count of purged tokens."""
    upload_dir = _get_upload_dir()
    now = time.time()
    purged = 0
    try:
        for meta_path in upload_dir.glob("*.meta"):
            try:
                meta = meta_path.read_text(encoding="utf-8")
                expires_at_str, _ = meta.split("|", 1)
                if now > int(expires_at_str):
                    token = meta_path.stem
                    _remove_upload_files(token, upload_dir)
                    purged += 1
            except Exception:
                pass
    except Exception:
        pass
    return purged


def is_upload_url(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(_UPLOAD_PREFIX)
