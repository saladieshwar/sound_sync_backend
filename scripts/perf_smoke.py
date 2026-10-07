"""Phase 6 QA: performance smoke test against a running API.

Run from backend/: python -m scripts.perf_smoke [base_url] [users]

`users` (default 10) throwaway accounts use the main read/write endpoints at the same time, each
pausing THINK_SECONDS between requests (a very fast-clicking user). Then all but one join the
same room in the same instant (a deliberate burst), and the controller's broadcasts are timed to
every listener. Each check has a p95 budget; any failed request also fails the run.
Throwaway users are deleted at the end. Requires seeded songs (`python -m scripts.seed`).

The API is a single process (the room hub is in memory), so requests that arrive together queue
behind each other; budgets are set for that, see docs/sync_tuning.md "Performance budgets".
"""

import json
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import httpx
from sqlalchemy import delete
from websockets.sync.client import connect as ws_connect

from app.db.session import SessionLocal
from app.models import User

PASSWORD = "perf-smoke-pass"
ROUNDS = 10
THINK_SECONDS = 0.1

# p95 budgets in ms (local API + DB, `users` concurrent clients). Login/register hash with bcrypt
# on purpose, so they get a larger budget.
BUDGETS = {
    "register": 1500,
    "login": 1500,
    "GET /auth/me": 150,
    "GET /songs": 150,
    "GET /songs/categories": 150,
    "GET /songs/albums": 150,
    "GET /songs/search": 150,
    "GET /songs/category": 150,
    "POST recently-played": 200,
    "GET recently-played": 150,
    "POST /rooms/{id}/join": 300,  # all listeners join in the same instant
    "GET /rooms/{id}": 150,
    "ws broadcast": 250,
}


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * 0.95) - 1)]


class Timer:
    def __init__(self):
        self.samples: dict[str, list[float]] = {}
        self.failures: list[str] = []

    def hit(self, label: str, call, expect: int = 200, think: bool = True):
        if think:
            time.sleep(THINK_SECONDS)
        start = time.perf_counter()
        response = call()
        self.samples.setdefault(label, []).append((time.perf_counter() - start) * 1000)
        if response.status_code != expect:
            self.failures.append(f"{label}: {response.status_code} {response.text[:120]}")
        return response


def user_session(base_url: str, timer: Timer, n: int) -> dict:
    http = httpx.Client(base_url=base_url, timeout=30)
    email = f"perf_{n}_{uuid.uuid4().hex[:8]}@soundsync.dev"
    timer.hit("register", lambda: http.post(
        "/auth/register", json={"username": f"perf{n}", "email": email, "password": PASSWORD}
    ), 201)
    login = timer.hit("login", lambda: http.post("/auth/login", json={"email": email, "password": PASSWORD}))
    token = login.json()["access_token"]
    http.headers["Authorization"] = f"Bearer {token}"

    songs = []
    for i in range(ROUNDS):
        timer.hit("GET /auth/me", lambda: http.get("/auth/me"))
        songs = timer.hit("GET /songs", lambda: http.get("/songs")).json()
        categories = timer.hit("GET /songs/categories", lambda: http.get("/songs/categories")).json()
        timer.hit("GET /songs/albums", lambda: http.get("/songs/albums"))
        song = songs[i % len(songs)]
        timer.hit("GET /songs/search", lambda: http.get("/songs/search", params={"q": song["title"][:3]}))
        timer.hit("GET /songs/category", lambda: http.get(f"/songs/category/{categories[i % len(categories)]}"))
        timer.hit("POST recently-played", lambda: http.post(f"/users/me/recently-played/{song['id']}"), 201)
        timer.hit("GET recently-played", lambda: http.get("/users/me/recently-played"))
    return {"http": http, "email": email, "token": token, "song_ids": [s["id"] for s in songs]}


def room_phase(base_url: str, timer: Timer, sessions: list[dict]) -> None:
    controller, *listeners = sessions
    room_id = controller["http"].post("/rooms", json={"name": "Perf smoke"}).json()["id"]

    def join(s):
        timer.hit("POST /rooms/{id}/join", lambda: s["http"].post(f"/rooms/{room_id}/join"), think=False)
        timer.hit("GET /rooms/{id}", lambda: s["http"].get(f"/rooms/{room_id}"))

    with ThreadPoolExecutor(len(listeners)) as pool:
        list(pool.map(join, listeners))

    ws_base = base_url.replace("http", "ws", 1)
    with ExitStack() as stack:
        sockets = [
            stack.enter_context(ws_connect(f"{ws_base}/rooms/{room_id}/ws?token={s['token']}", open_timeout=10))
            for s in sessions
        ]
        for ws in sockets:
            _expect(ws, "room_state")
        songs = controller["song_ids"]
        for i in range(ROUNDS):
            for event, payload in (
                ("song_change", {"song_id": songs[i % len(songs)], "position_seconds": 0}),
                ("seek", {"position_seconds": 10 + i}),
                ("pause", {"position_seconds": 11 + i}),
                ("play", {"position_seconds": 11 + i}),
            ):
                sent = time.perf_counter()
                sockets[0].send(json.dumps({"type": event, "payload": payload}))
                for ws in sockets[1:]:
                    _expect(ws, event)
                    timer.samples.setdefault("ws broadcast", []).append((time.perf_counter() - sent) * 1000)
                _expect(sockets[0], event)
    controller["http"].post(f"/rooms/{room_id}/leave")


def _expect(ws, event: str) -> dict:
    deadline = time.monotonic() + 10
    while True:
        message = json.loads(ws.recv(timeout=max(0.01, deadline - time.monotonic())))
        if message["type"] == event:
            return message
        if message["type"] not in ("user_joined", "user_left"):
            raise AssertionError(f"expected {event}, got {message}")


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    users = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    timer = Timer()
    sessions: list[dict] = []
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(users) as pool:
            sessions = list(pool.map(lambda n: user_session(base_url, timer, n), range(users)))
        room_phase(base_url, timer, sessions)
    finally:
        emails = [s["email"] for s in sessions]
        if emails:
            with SessionLocal() as db:
                db.execute(delete(User).where(User.email.in_(emails)))
                db.commit()

    total = sum(len(v) for v in timer.samples.values())
    print(f"{users} concurrent users, {total} timed operations in {time.perf_counter() - started:.1f}s\n")
    print(f"{'check':24} {'n':>5} {'p50 ms':>8} {'p95 ms':>8} {'budget':>8}  result")
    ok = not timer.failures
    for label, budget in BUDGETS.items():
        values = timer.samples.get(label, [])
        if not values:
            continue
        passed = p95(values) <= budget
        ok &= passed
        print(f"{label:24} {len(values):5} {statistics.median(values):8.1f} {p95(values):8.1f} "
              f"{budget:8}  {'PASS' if passed else 'FAIL'}")
    for failure in timer.failures[:10]:
        print(f"  request failed: {failure}")
    print(f"\nErrors: {len(timer.failures)}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
