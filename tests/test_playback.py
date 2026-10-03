"""Phase 4 playback support: seed audio, media streaming, play-event logging, history query plan."""

import uuid
import wave
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import RecentlyPlayed
from scripts.benchmark_recently_played import explain, seed_history
from scripts.seed import AUDIO_SAMPLE_RATE, SONGS, audio_url_for, build_wav_frames, write_wav

RECENT = "/users/me/recently-played"


# --- seed audio -------------------------------------------------------------


def test_wav_frames_are_exactly_the_song_length_and_fade_to_silence():
    frames = build_wav_frames("sad", 3)
    assert len(frames) == 3 * AUDIO_SAMPLE_RATE
    assert frames[-1] == 128  # 8-bit unsigned PCM silence
    assert max(frames) - min(frames) > 100  # audible, not silence


def test_write_wav_produces_a_playable_file_matching_duration(tmp_path):
    path = tmp_path / "song.wav"
    write_wav(path, "melody", 5)
    with wave.open(str(path)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == AUDIO_SAMPLE_RATE
        assert wav.getnframes() / wav.getframerate() == 5


def test_write_wav_is_idempotent(tmp_path):
    path = tmp_path / "song.wav"
    write_wav(path, "love", 2)
    mtime = path.stat().st_mtime_ns
    write_wav(path, "love", 2)
    assert path.stat().st_mtime_ns == mtime


def test_every_seed_song_has_its_own_audio_url():
    urls = [audio_url_for(s["title"]) for s in SONGS]
    assert len(set(urls)) == len(SONGS)
    assert all(u.startswith(f"{settings.MEDIA_URL_PREFIX}/audio/") and u.endswith(".wav") for u in urls)


def test_catalog_songs_point_at_seed_audio(client, catalog):
    song = client.get(f"/songs/{catalog['Rise Up'].id}").json()
    assert song["audio_url"] == "/media/audio/rise-up.wav"
    assert song["duration_seconds"] == 187


# --- media streaming (seek needs HTTP range support) --------------------------


@pytest.fixture
def media_audio_file():
    audio_dir = Path(settings.MEDIA_ROOT) / "audio"
    path = audio_dir / f"test-{uuid.uuid4().hex}.wav"
    write_wav(path, "melody", 2)
    try:
        yield f"{settings.MEDIA_URL_PREFIX}/audio/{path.name}", path.stat().st_size
    finally:
        path.unlink(missing_ok=True)


def test_audio_is_served_with_audio_content_type(client, media_audio_file):
    url, size = media_audio_file
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] in {"audio/wav", "audio/x-wav", "audio/wave"}
    assert int(response.headers["content-length"]) == size
    assert response.headers.get("accept-ranges") == "bytes"


def test_audio_supports_range_requests_for_seeking(client, media_audio_file):
    url, size = media_audio_file
    response = client.get(url, headers={"Range": "bytes=8000-8999"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 8000-8999/{size}"
    assert len(response.content) == 1000


def test_missing_audio_is_structured_404(client):
    response = client.get("/media/audio/does-not-exist.wav")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- play-event logging (PLY-06) ----------------------------------------------


def test_each_play_event_is_logged_for_the_right_user(client, db, catalog, login_headers):
    alice, bob = login_headers(username="alice"), login_headers(username="bob")
    rise_up, grey_rain = catalog["Rise Up"].id, catalog["Grey Rain"].id

    for song_id in [rise_up, rise_up, grey_rain]:
        assert client.post(f"{RECENT}/{song_id}", headers=alice).status_code == 201
    assert client.post(f"{RECENT}/{grey_rain}", headers=bob).status_code == 201

    alice_id = client.get("/auth/me", headers=alice).json()["id"]
    bob_id = client.get("/auth/me", headers=bob).json()["id"]
    count = lambda uid: db.scalar(  # noqa: E731
        select(func.count()).select_from(RecentlyPlayed).where(RecentlyPlayed.user_id == uid)
    )
    assert count(alice_id) == 3
    assert count(bob_id) == 1


# --- DATA: recently-played lookups stay index-only ----------------------------


def test_recently_played_query_uses_index_without_sort(db, catalog):
    conn = db.connection()
    user_id = seed_history(conn, users=200, plays_per_user=100)

    plan = explain(conn, user_id)

    assert "ix_recently_played_user_played_at_id" in plan["indexes"]
    assert not any("Sort" in node for node in plan["node_types"]), plan["node_types"]
    assert plan["execution_ms"] < 50
