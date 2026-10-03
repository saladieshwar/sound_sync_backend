"""Seed fixtures for local dev and QA. Run from backend/: python -m scripts.seed

Idempotent: users are matched by email, songs by (title, artist). Album cover art is
generated as SVG under MEDIA_ROOT/covers so the catalog renders without external assets.
"""

import re
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Song, User
from app.repositories import user_repo

USERS = [
    {"username": "admin", "email": "admin@soundsync.dev", "password": "admin12345", "is_admin": True},
    {"username": "alice", "email": "alice@soundsync.dev", "password": "alice12345", "is_admin": False},
    {"username": "bob", "email": "bob@soundsync.dev", "password": "bob1234567", "is_admin": False},
]

SONGS = [
    {"title": "Evening Breeze", "artist": "Aria Nova", "album": "Calm Skies", "category": "melody", "duration_seconds": 214},
    {"title": "Moonlit Path", "artist": "Aria Nova", "album": "Calm Skies", "category": "melody", "duration_seconds": 198},
    {"title": "Heartstrings", "artist": "The Lovelines", "album": "Forever Yours", "category": "love", "duration_seconds": 231},
    {"title": "Only You", "artist": "The Lovelines", "album": "Forever Yours", "category": "love", "duration_seconds": 205},
    {"title": "Rise Up", "artist": "Peak Drive", "album": "Unstoppable", "category": "motivation", "duration_seconds": 187},
    {"title": "Keep Going", "artist": "Peak Drive", "album": "Unstoppable", "category": "motivation", "duration_seconds": 176},
    {"title": "Grey Rain", "artist": "Blue Hours", "album": "Quiet Rooms", "category": "sad", "duration_seconds": 242},
    {"title": "Letters Unsent", "artist": "Blue Hours", "album": "Quiet Rooms", "category": "sad", "duration_seconds": 219},
]

CATEGORY_COLORS = {
    "melody": ("#0ea5e9", "#6366f1"),
    "love": ("#f43f5e", "#a855f7"),
    "motivation": ("#f59e0b", "#ef4444"),
    "sad": ("#475569", "#1e3a8a"),
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def cover_url_for(album: str) -> str:
    return f"{settings.MEDIA_URL_PREFIX}/covers/{_slug(album)}.svg"


def _cover_svg(album: str, artist: str, category: str) -> str:
    start, end = CATEGORY_COLORS.get(category, ("#10b981", "#0f172a"))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{start}"/>
      <stop offset="1" stop-color="{end}"/>
    </linearGradient>
  </defs>
  <rect width="300" height="300" fill="url(#g)"/>
  <circle cx="150" cy="120" r="56" fill="none" stroke="#ffffff" stroke-opacity="0.35" stroke-width="10"/>
  <circle cx="150" cy="120" r="12" fill="#ffffff" fill-opacity="0.6"/>
  <text x="150" y="230" text-anchor="middle" font-family="sans-serif" font-size="24" font-weight="700" fill="#ffffff">{escape(album)}</text>
  <text x="150" y="260" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#ffffff" fill-opacity="0.8">{escape(artist)}</text>
</svg>
"""


def write_covers() -> None:
    covers_dir = Path(settings.MEDIA_ROOT) / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for s in SONGS:
        if s["album"] in seen:
            continue
        seen.add(s["album"])
        path = covers_dir / f"{_slug(s['album'])}.svg"
        path.write_text(_cover_svg(s["album"], s["artist"], s["category"]), encoding="utf-8")


def run() -> None:
    write_covers()
    with SessionLocal() as db:
        for u in USERS:
            if not user_repo.get_by_email(db, u["email"]):
                db.add(
                    User(
                        username=u["username"],
                        email=u["email"],
                        password_hash=hash_password(u["password"]),
                        is_admin=u["is_admin"],
                    )
                )

        for i, s in enumerate(SONGS, start=1):
            song = db.scalars(
                select(Song).where(Song.title == s["title"], Song.artist == s["artist"])
            ).first()
            if song is None:
                db.add(
                    Song(
                        **s,
                        audio_url=f"{settings.MEDIA_URL_PREFIX}/audio/sample-{i}.mp3",
                        cover_url=cover_url_for(s["album"]),
                    )
                )
            else:
                for field, value in s.items():
                    setattr(song, field, value)
                song.cover_url = cover_url_for(s["album"])

        db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    run()
