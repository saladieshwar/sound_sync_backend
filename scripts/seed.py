"""Seed fixtures for local dev and QA. Run from backend/: python -m scripts.seed"""

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


def run() -> None:
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

        if db.query(Song).count() == 0:
            for i, s in enumerate(SONGS, start=1):
                db.add(
                    Song(
                        **s,
                        audio_url=f"/media/audio/sample-{i}.mp3",
                        cover_url=f"/media/covers/sample-{i}.jpg",
                    )
                )

        db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    run()
