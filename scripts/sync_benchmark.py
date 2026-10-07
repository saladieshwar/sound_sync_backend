"""Phase 6 RT: playback-sync quality under realistic network conditions.

Run from backend/ while the API is running (needs two songs: `python -m scripts.seed`):

    python -m scripts.sync_benchmark [base_url] [profile ...]

Profiles (see scripts/netem_proxy.py): lan, wifi, 4g, poor. Default: all four.

For each profile, three throwaway users join one room; every WebSocket goes through a proxy that
adds that profile's delay/jitter/loss spikes (REST calls stay direct). Two things are measured:

* delivery latency - controller sends play/pause/seek/song_change -> each listener receives it.
  This is how long listeners take to *react* to a control change.
* timeline agreement - each listener runs the same clock estimate as the browser
  (`frontend/src/realtime/serverClock.js`: min-RTT sample of `time_sync` round trips) with a
  deliberately wrong device clock (random skew up to ±3 s). Since every client positions audio at
  `position + (serverNow - server_ts)`, the difference between two listeners' clock errors is
  exactly how far apart their audio would be. This is the number listeners hear.

The throwaway users (and their room) are deleted at the end.
"""

import json
import random
import statistics
import sys
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select
from websockets.sync.client import connect as ws_connect

from app.db.session import SessionLocal
from app.models import Song, User
from scripts.netem_proxy import PROFILES, NetemProxy

PASSWORD = "sync-bench-pass"
RECV_TIMEOUT = 10.0
MAX_CLOCK_SAMPLES = 10  # serverClock.js MAX_SAMPLES
INITIAL_SAMPLES = 5  # useRoomSocket.js: 5 time_sync probes on connect
MAX_SKEW_MS = 3000

# Agreed targets (docs/sync_tuning.md). "Normal" = lan / wifi / 4g.
TARGETS = {
    "lan": {"delivery_p95_ms": 250, "agreement_p95_ms": 40},
    "wifi": {"delivery_p95_ms": 250, "agreement_p95_ms": 40},
    "4g": {"delivery_p95_ms": 250, "agreement_p95_ms": 40},
    # Degraded network: must stay under the frontend resync threshold (150 ms) so the player
    # never flaps between corrections, and under the 500 ms drift tolerance for reactions.
    "poor": {"delivery_p95_ms": 500, "agreement_p95_ms": 150},
}


class ServerClock:
    """Python mirror of frontend/src/realtime/serverClock.js."""

    def __init__(self):
        self.samples: list[tuple[float, float]] = []  # (rtt, offset)

    def add_sample(self, sent_at: float, server_ts: float, received_at: float) -> None:
        if received_at < sent_at:
            return
        rtt = received_at - sent_at
        self.samples = [*self.samples, (rtt, server_ts - (sent_at + rtt / 2))][-MAX_CLOCK_SAMPLES:]

    def offset(self) -> float:
        return min(self.samples)[1] if self.samples else 0.0


class Listener:
    def __init__(self, base_url: str, ws_address: str, name: str, skew_ms: float):
        self.http = httpx.Client(base_url=base_url, timeout=10)
        self.ws_address = ws_address
        self.skew_ms = skew_ms
        self.email = f"syncbench_{name}_{uuid.uuid4().hex[:8]}@soundsync.dev"
        reg = self.http.post(
            "/auth/register", json={"username": name, "email": self.email, "password": PASSWORD}
        )
        reg.raise_for_status()
        self.id = reg.json()["id"]
        token = self.http.post("/auth/login", json={"email": self.email, "password": PASSWORD})
        self.token = token.json()["access_token"]
        self.http.headers["Authorization"] = f"Bearer {self.token}"
        self.ws = None

    def local_ms(self) -> float:
        """This device's (wrong) wall clock."""
        return time.time() * 1000 + self.skew_ms

    def connect(self, room_id: str) -> None:
        self._stack = ExitStack()
        self.ws = self._stack.enter_context(
            ws_connect(f"ws://{self.ws_address}/rooms/{room_id}/ws?token={self.token}", open_timeout=10)
        )
        self.expect("room_state")

    def close(self) -> None:
        if self.ws is not None:
            self._stack.close()
            self.ws = None

    def send(self, event: str, **payload) -> None:
        self.ws.send(json.dumps({"type": event, "payload": payload}))

    def expect(self, event: str) -> dict:
        deadline = time.monotonic() + RECV_TIMEOUT
        while True:
            message = json.loads(self.ws.recv(timeout=max(0.01, deadline - time.monotonic())))
            if message["type"] == event:
                return message
            if message["type"] not in ("user_joined", "user_left"):
                raise AssertionError(f"expected {event}, got {message}")

    def clock_error_ms(self, samples: int = INITIAL_SAMPLES) -> float:
        """Estimated server offset minus the true one (true offset = -skew: same host clock)."""
        clock = ServerClock()
        for _ in range(samples):
            sent = self.local_ms()
            self.send("time_sync", client_ts=sent)
            reply = self.expect("time_sync")
            clock.add_sample(reply["payload"]["client_ts"], reply["server_ts"], self.local_ms())
        return clock.offset() + self.skew_ms


@dataclass
class Result:
    profile: str
    delivery_ms: list[float] = field(default_factory=list)
    agreement_ms: list[float] = field(default_factory=list)
    clock_error_ms: list[float] = field(default_factory=list)

    @staticmethod
    def p(values: list[float], q: float) -> float:
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * q) - 1))] if ordered else 0.0

    def summary(self) -> dict:
        return {
            "delivery_p50_ms": statistics.median(self.delivery_ms),
            "delivery_p95_ms": self.p(self.delivery_ms, 0.95),
            "delivery_max_ms": max(self.delivery_ms),
            "clock_error_p95_ms": self.p([abs(e) for e in self.clock_error_ms], 0.95),
            "agreement_p50_ms": statistics.median(self.agreement_ms),
            "agreement_p95_ms": self.p(self.agreement_ms, 0.95),
            "agreement_max_ms": max(self.agreement_ms),
        }

    def passed(self) -> bool:
        s, t = self.summary(), TARGETS[self.profile]
        return s["delivery_p95_ms"] <= t["delivery_p95_ms"] and s["agreement_p95_ms"] <= t["agreement_p95_ms"]


def run_profile(
    base_url: str, profile_name: str, song_ids: list[int], *, rounds: int = 10, trials: int = 10,
    seed: int = 7,
) -> Result:
    target = urlparse(base_url)
    rng = random.Random(seed)
    result = Result(profile_name)
    people: list[Listener] = []
    with NetemProxy(target.hostname, target.port or 80, PROFILES[profile_name], seed=seed) as proxy:
        try:
            for name in ("ctrl", "ann", "ben"):
                skew = rng.uniform(-MAX_SKEW_MS, MAX_SKEW_MS)
                people.append(Listener(base_url, proxy.address, name, skew))
            controller, *listeners = people
            room_id = controller.http.post("/rooms", json={"name": "Sync bench"}).json()["id"]
            for listener in listeners:
                listener.http.post(f"/rooms/{room_id}/join").raise_for_status()
            for person in people:
                person.connect(room_id)

            for i in range(rounds):
                for event, payload in (
                    ("song_change", {"song_id": song_ids[i % len(song_ids)], "position_seconds": 0}),
                    ("seek", {"position_seconds": 20 + i}),
                    ("pause", {"position_seconds": 21 + i}),
                    ("play", {"position_seconds": 21 + i}),
                ):
                    sent = time.perf_counter()
                    controller.send(event, **payload)
                    for listener in listeners:
                        listener.expect(event)
                        result.delivery_ms.append((time.perf_counter() - sent) * 1000)
                    controller.expect(event)

            for _ in range(trials):
                errors = [listener.clock_error_ms() for listener in listeners]
                result.clock_error_ms += errors
                result.agreement_ms.append(abs(errors[0] - errors[1]))
        finally:
            for person in people:
                try:
                    person.close()
                except Exception:
                    pass
            with SessionLocal() as db:
                db.execute(delete(User).where(User.email.in_([p.email for p in people])))
                db.commit()
    return result


def main() -> int:
    args = sys.argv[1:]
    base_url = args.pop(0) if args and args[0].startswith("http") else "http://127.0.0.1:8000"
    profiles = args or list(PROFILES)

    with SessionLocal() as db:
        song_ids = list(db.scalars(select(Song.id).order_by(Song.id).limit(2)))
    if len(song_ids) < 2:
        raise SystemExit("Need at least two songs: run `python -m scripts.seed` first.")

    ok = True
    print(f"{'profile':8} {'network':22} {'delivery p50/p95/max ms':>26} "
          f"{'clock err p95':>14} {'agreement p50/p95/max ms':>26}  result")
    for name in profiles:
        r = run_profile(base_url, name, song_ids)
        s = r.summary()
        ok &= r.passed()
        t = TARGETS[name]
        print(
            f"{name:8} {PROFILES[name].rtt_label:22} "
            f"{s['delivery_p50_ms']:8.1f} /{s['delivery_p95_ms']:7.1f} /{s['delivery_max_ms']:7.1f} "
            f"{s['clock_error_p95_ms']:14.1f} "
            f"{s['agreement_p50_ms']:8.1f} /{s['agreement_p95_ms']:7.1f} /{s['agreement_max_ms']:7.1f}  "
            f"{'PASS' if r.passed() else 'FAIL'} "
            f"(targets {t['delivery_p95_ms']} / {t['agreement_p95_ms']} ms)"
        )
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
