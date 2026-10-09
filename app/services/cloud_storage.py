"""Cloudinary storage for uploads, used when CLOUDINARY_URL is set (signed REST API, no SDK)."""

import hashlib
import logging
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import status

from app.core.config import settings
from app.core.errors import AppError, ErrorCode

log = logging.getLogger(__name__)

_API = "https://api.cloudinary.com/v1_1"
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
# https://res.cloudinary.com/<cloud>/<image|video|raw>/upload/[v123/]<public_id>.<ext>
_DELIVERY = re.compile(r"^/(?P<cloud>[^/]+)/(?P<type>image|video|raw)/upload/(?:v\d+/)?(?P<id>.+?)(?:\.\w+)?$")


def _credentials() -> tuple[str, str, str] | None:
    parts = urlsplit(settings.CLOUDINARY_URL.strip())
    if parts.scheme != "cloudinary" or not (parts.username and parts.password and parts.hostname):
        return None
    return parts.username, parts.password, parts.hostname


def enabled() -> bool:
    return _credentials() is not None


def _signed(params: dict, api_key: str, api_secret: str) -> dict:
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params))
    signature = hashlib.sha1(f"{to_sign}{api_secret}".encode()).hexdigest()
    return {**params, "api_key": api_key, "signature": signature}


def upload(path: Path, subdir: str, resource_type: str) -> str:
    """Uploads a local file and returns its permanent https URL."""
    api_key, api_secret, cloud = _credentials()
    params = {
        "folder": f"{settings.CLOUDINARY_FOLDER}/{subdir}",
        "public_id": uuid.uuid4().hex,
        "timestamp": int(time.time()),
    }
    try:
        with path.open("rb") as f:
            response = httpx.post(
                f"{_API}/{cloud}/{resource_type}/upload",
                data=_signed(params, api_key, api_secret),
                files={"file": (path.name, f)},
                timeout=_TIMEOUT,
            )
        response.raise_for_status()
        return response.json()["secure_url"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        detail = getattr(getattr(exc, "response", None), "text", "")[:300]
        log.error("Cloudinary upload failed: %s %s", exc, detail)
        raise AppError(
            ErrorCode.HTTP_ERROR,
            "Could not store the file in cloud storage. Please try again.",
            status.HTTP_502_BAD_GATEWAY,
        ) from exc


def owns(url: str | None) -> bool:
    creds = _credentials()
    if not url or creds is None:
        return False
    parts = urlsplit(url)
    match = _DELIVERY.match(parts.path)
    return parts.hostname == "res.cloudinary.com" and bool(match) and match["cloud"] == creds[2]


def delete(url: str) -> None:
    """Best effort: a file that cannot be deleted only wastes storage."""
    api_key, api_secret, cloud = _credentials()
    match = _DELIVERY.match(urlsplit(url).path)
    params = {"public_id": match["id"], "invalidate": "true", "timestamp": int(time.time())}
    try:
        httpx.post(
            f"{_API}/{cloud}/{match['type']}/destroy",
            data=_signed(params, api_key, api_secret),
            timeout=_TIMEOUT,
        ).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Cloudinary delete failed for %s: %s", url, exc)
