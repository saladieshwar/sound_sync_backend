"""GET /media/<subdir>/<name>: files under MEDIA_ROOT (seed catalog, local uploads), falling back
to uploads stored in the media_files table. Range requests are honoured (audio seeking)."""

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import MediaFile
from app.services import media_service

router = APIRouter()

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
# Uploaded names are random and never reused, so clients may cache them for good.
_IMMUTABLE = "public, max-age=31536000, immutable"


def _byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Inclusive (start, end) for a single-range header; None means "send everything"."""
    match = _RANGE.match((header or "").strip())
    if not match or match.groups() == ("", ""):
        return None
    first, last = match.groups()
    if first:
        start, end = int(first), min(int(last), size - 1) if last else size - 1
    else:
        start, end = max(size - int(last), 0), size - 1
    if start >= size or start > end:
        raise HTTPException(
            status.HTTP_416_RANGE_NOT_SATISFIABLE, headers={"Content-Range": f"bytes */{size}"}
        )
    return start, end


@router.api_route("/{file_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def get_media(file_path: str, request: Request, db: Session = Depends(get_db)) -> Response:
    url = f"{settings.MEDIA_URL_PREFIX.rstrip('/')}/{file_path}"
    path = media_service.media_path(url)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if path.is_file():
        return FileResponse(path)

    row = db.execute(
        select(MediaFile.content_type, MediaFile.size).where(MediaFile.key == media_service.media_key(url))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    content_type, size = row
    headers = {"Accept-Ranges": "bytes", "Cache-Control": _IMMUTABLE}
    byte_range = _byte_range(request.headers.get("range"), size)
    start, end = byte_range or (0, size - 1)
    length = end - start + 1
    headers["Content-Length"] = str(length)
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    code = status.HTTP_206_PARTIAL_CONTENT if byte_range else status.HTTP_200_OK
    if request.method == "HEAD":
        return Response(status_code=code, headers=headers, media_type=content_type)
    data = db.execute(
        select(func.substring(MediaFile.data, start + 1, length)).where(MediaFile.key == media_service.media_key(url))
    ).scalar_one()
    return Response(content=bytes(data), status_code=code, headers=headers, media_type=content_type)
