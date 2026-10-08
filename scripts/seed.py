"""Seed fixtures for local dev and QA. Run from backend/: python -m scripts.seed

`--catalog-only` skips the seed accounts (their passwords are public) for hosted deployments.

Idempotent: users are matched by email, songs by (title, artist). Album cover art (SVG) and
sample audio (WAV, exactly `duration_seconds` long) are generated under MEDIA_ROOT so the
catalog renders and plays end-to-end without external assets.
"""

import math
import re
import sys
import wave
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


AUDIO_SAMPLE_RATE = 8000  # 8 kHz, 8-bit mono: ~8 KB per second of audio
_NOTE_SECONDS = 0.5

# Four-note arpeggio (Hz) looped for each category's sample track.
CATEGORY_ARPEGGIOS = {
    "melody": (261.63, 329.63, 392.00, 523.25),  # C major
    "love": (349.23, 440.00, 523.25, 659.25),  # F major 7-ish
    "motivation": (392.00, 493.88, 587.33, 783.99),  # G major
    "sad": (220.00, 261.63, 329.63, 440.00),  # A minor
}


def audio_url_for(title: str) -> str:
    return f"{settings.MEDIA_URL_PREFIX}/audio/{_slug(title)}.wav"


def _arpeggio_loop(category: str) -> bytes:
    notes = CATEGORY_ARPEGGIOS.get(category, CATEGORY_ARPEGGIOS["melody"])
    per_note = int(AUDIO_SAMPLE_RATE * _NOTE_SECONDS)
    out = bytearray()
    for freq in notes:
        for n in range(per_note):
            t = n / AUDIO_SAMPLE_RATE
            envelope = math.exp(-4.0 * t)
            value = envelope * (0.7 * math.sin(2 * math.pi * freq * t)
                                + 0.3 * math.sin(math.pi * freq * t))
            out.append(128 + int(90 * value))
    return bytes(out)


def build_wav_frames(category: str, duration_seconds: int) -> bytes:
    """8-bit unsigned PCM frames, exactly `duration_seconds` long, fading out over the last second."""
    total = AUDIO_SAMPLE_RATE * duration_seconds
    loop = _arpeggio_loop(category)
    frames = bytearray((loop * (total // len(loop) + 1))[:total])
    fade = min(AUDIO_SAMPLE_RATE, total)
    for i in range(fade):
        idx = total - fade + i
        frames[idx] = 128 + int((frames[idx] - 128) * (1 - i / fade))
    return bytes(frames)


def write_wav(path: Path, category: str, duration_seconds: int) -> None:
    expected_size = 44 + AUDIO_SAMPLE_RATE * duration_seconds
    if path.exists() and path.stat().st_size == expected_size:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(AUDIO_SAMPLE_RATE)
        wav.writeframes(build_wav_frames(category, duration_seconds))


def write_audio() -> None:
    audio_dir = Path(settings.MEDIA_ROOT) / "audio"
    for s in SONGS:
        write_wav(audio_dir / f"{_slug(s['title'])}.wav", s["category"], s["duration_seconds"])


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


def run(with_users: bool = True) -> None:
    write_covers()
    write_audio()
    with SessionLocal() as db:
        for u in USERS if with_users else []:
            if not user_repo.get_by_email(db, u["email"]):
                db.add(
                    User(
                        username=u["username"],
                        email=u["email"],
                        password_hash=hash_password(u["password"]),
                        is_admin=u["is_admin"],
                    )
                )

        for s in SONGS:
            song = db.scalars(
                select(Song).where(Song.title == s["title"], Song.artist == s["artist"])
            ).first()
            if song is None:
                song = Song(**s)
                db.add(song)
            else:
                for field, value in s.items():
                    setattr(song, field, value)
            song.audio_url = audio_url_for(s["title"])
            song.cover_url = cover_url_for(s["album"])

        db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    run(with_users="--catalog-only" not in sys.argv)
