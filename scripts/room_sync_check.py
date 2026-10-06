"""Live multi-client room sync check (QA evidence for Phase 5).

Run from backend/ while the API is running:

    python -m scripts.room_sync_check [base_url] [rounds]

Default base_url is http://127.0.0.1:8000. Registers three throwaway users, creates a room,
joins it via REST (one by Room ID, one by lower-case Room ID from the join link), connects three
sockets, then drives play/pause/seek/song-change from the controller, transfers control both
ways, drops and reconnects a client, and closes the room by having the admin leave.

Delivery latency is measured from the moment the controller sends an event until each client
receives the broadcast. The throwaway users (and their rooms) are deleted at the end.
Requires at least two songs (run `python -m scripts.seed` first).
"""

import json
import statistics
import sys
import time
import uuid

import httpx
from sqlalchemy import delete, select
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models import Song, User

PASSWORD = "sync-check-pass"
DRIFT_TOLERANCE_MS = 500
RECV_TIMEOUT = 5.0


class Client:
    def __init__(self, base_url: str, name: str):
        self.base_url = base_url
        self.http = httpx.Client(base_url=base_url, timeout=10)
        self.email = f"synccheck_{name}_{uuid.uuid4().hex[:8]}@soundsync.dev"
        reg = self.http.post(
            "/auth/register", json={"username": name, "email": self.email, "password": PASSWORD}
        )
        reg.raise_for_status()
        self.id = reg.json()["id"]
        login = self.http.post("/auth/login", json={"email": self.email, "password": PASSWORD})
        self.token = login.json()["access_token"]
        self.http.headers["Authorization"] = f"Bearer {self.token}"
        self.ws = None

    def connect(self, room_id: str) -> dict:
        ws_url = self.base_url.replace("http", "ws", 1)
        self.ws = connect(f"{ws_url}/rooms/{room_id}/ws?token={self.token}", open_timeout=5)
        self.ws.__enter__()
        return self.expect("room_state")["payload"]

    def disconnect(self) -> None:
        self.ws.__exit__(None, None, None)
        self.ws = None

    def send(self, event: str, **payload) -> float:
        sent = time.perf_counter()
        self.ws.send(json.dumps({"type": event, "payload": payload}))
        return sent

    def expect(self, event: str) -> dict:
        deadline = time.monotonic() + RECV_TIMEOUT
        while True:
            message = json.loads(self.ws.recv(timeout=max(0.01, deadline - time.monotonic())))
            if message["type"] == event:
                return message
            if message["type"] not in ("user_joined", "user_left"):
                raise AssertionError(f"expected {event}, got {message}")


def check(label: str, ok: bool) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        raise SystemExit(1)


def broadcast_round(controller: Client, everyone: list[Client], event: str, **payload) -> list[float]:
    sent = controller.send(event, **payload)
    latencies = []
    for client in everyone:
        message = client.expect(event)
        latencies.append((time.perf_counter() - sent) * 1000)
        assert message["sender_user_id"] == controller.id, message
    return latencies


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    with SessionLocal() as db:
        song_ids = list(db.scalars(select(Song.id).order_by(Song.id).limit(2)))
    if len(song_ids) < 2:
        raise SystemExit("Need at least two songs: run `python -m scripts.seed` first.")

    clients: list[Client] = []
    try:
        for name in ("admin", "bob", "carol"):
            clients.append(Client(base_url, name))
        admin, bob, carol = everyone = clients

        print("Room lifecycle (REST)")
        room = admin.http.post("/rooms", json={"name": "Sync check"}).json()
        room_id = room["id"]
        check(f"room {room_id} created, join link {room['join_link']}", len(room_id) == 8)
        check("joined by Room ID", bob.http.post(f"/rooms/{room_id}/join").status_code == 200)
        link_id = room["join_link"].rsplit("/", 1)[-1].lower()
        check("joined via join link", carol.http.post(f"/rooms/{link_id}/join").status_code == 200)

        print("Sockets")
        for client in everyone:
            state = client.connect(room_id)
        check("all three clients received room_state", len(state["online_user_ids"]) == 3)

        print(f"Playback sync ({rounds} rounds x 4 events x 3 clients)")
        latencies: list[float] = []
        for i in range(rounds):
            song = song_ids[i % 2]
            latencies += broadcast_round(admin, everyone, "song_change", song_id=song, position_seconds=0)
            latencies += broadcast_round(admin, everyone, "seek", position_seconds=30 + i)
            latencies += broadcast_round(admin, everyone, "pause", position_seconds=31 + i)
            latencies += broadcast_round(admin, everyone, "play", position_seconds=31 + i)
        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95) - 1]
        print(f"  delivery latency ms: p50={p50:.1f} p95={p95:.1f} max={latencies[-1]:.1f}")
        check(f"p95 delivery within drift tolerance ({DRIFT_TOLERANCE_MS} ms)", p95 < DRIFT_TOLERANCE_MS)

        print("Controller validation")
        bob.send("pause", position_seconds=1)
        check("non-controller rejected", bob.expect("error")["payload"]["code"] == "NOT_ROOM_CONTROLLER")

        print("Control transfer")
        admin.http.post(f"/rooms/{room_id}/transfer-access", json={"target_user_id": bob.id})
        check("admin -> bob broadcast", all(
            c.expect("access_transfer")["payload"]["controller_user_id"] == bob.id for c in everyone
        ))
        broadcast_round(bob, everyone, "seek", position_seconds=10)
        check("bob drives playback", True)
        bob.http.post(f"/rooms/{room_id}/transfer-access", json={"target_user_id": admin.id})
        check("bob -> admin broadcast", all(
            c.expect("access_transfer")["payload"]["controller_user_id"] == admin.id for c in everyone
        ))

        print("Network drop and reconnect")
        carol.disconnect()
        check("drop reported", admin.expect("user_left")["payload"]["reason"] == "disconnected")
        broadcast_round(admin, [admin, bob], "seek", position_seconds=77)
        state = carol.connect(room_id)
        check("reconnect resyncs position", state["position_seconds"] == 77.0)

        print("Admin leaves mid-session")
        admin.http.post(f"/rooms/{room_id}/leave")
        for client in (bob, carol):
            client.expect("room_closed")
        check("room_closed delivered to everyone", True)
        check("room is closed", bob.http.get(f"/rooms/{room_id}").status_code == 410)
        print("All room sync checks passed.")
    finally:
        for client in clients:
            if client.ws is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
        with SessionLocal() as db:
            db.execute(delete(User).where(User.email.in_([c.email for c in clients])))
            db.commit()


if __name__ == "__main__":
    main()
