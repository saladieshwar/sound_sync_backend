"""Phase 6 RT: sync stays within the agreed tolerance under simulated network conditions.

Each WebSocket goes through scripts.netem_proxy (delay, jitter, loss spikes); targets and method
are documented in docs/sync_tuning.md. Full-length runs: `python -m scripts.sync_benchmark`.
"""

import socket
import threading
import time

import pytest

from scripts.netem_proxy import PROFILES, NetemProxy, Profile
from scripts.sync_benchmark import TARGETS, ServerClock, run_profile
from tests.live import cleanup_rows, live_server, make_songs


@pytest.fixture(scope="module")
def server():
    with live_server() as base:
        yield base


@pytest.fixture(scope="module")
def songs():
    with cleanup_rows() as rows:
        yield make_songs(rows)


@pytest.mark.parametrize("profile", list(PROFILES))
def test_sync_meets_targets_under_network_profile(server, songs, profile):
    result = run_profile(f"http://{server}", profile, songs, rounds=5, trials=6)
    summary = result.summary()
    assert len(result.delivery_ms) == 5 * 4 * 2
    assert summary["delivery_p95_ms"] <= TARGETS[profile]["delivery_p95_ms"], summary
    assert summary["agreement_p95_ms"] <= TARGETS[profile]["agreement_p95_ms"], summary
    # Listeners start with clocks up to 3 s wrong; the estimate must cancel almost all of it.
    assert summary["clock_error_p95_ms"] < TARGETS[profile]["agreement_p95_ms"], summary


def test_server_clock_mirror_uses_min_rtt_sample():
    clock = ServerClock()
    assert clock.offset() == 0
    clock.add_sample(1000, 6100, 1200)  # rtt 200 -> offset 5000
    clock.add_sample(2000, 7020, 2040)  # rtt 40  -> offset 5000
    clock.add_sample(3000, 8300, 3100)  # rtt 100 -> offset 5250
    assert clock.offset() == 5000
    clock.add_sample(4000, 9000, 3990)  # receive before send: ignored
    assert len(clock.samples) == 3


def _echo_server():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def serve():
        conn, _ = listener.accept()
        with conn:
            while data := conn.recv(4096):
                conn.sendall(data)

    threading.Thread(target=serve, daemon=True).start()
    return listener


def test_proxy_adds_delay_and_preserves_order():
    listener = _echo_server()
    profile = Profile("test", delay_ms=40, jitter_ms=30)
    with NetemProxy(*listener.getsockname(), profile, seed=1) as proxy:
        with socket.create_connection(("127.0.0.1", proxy.port)) as conn:
            start = time.perf_counter()
            for i in range(20):
                conn.sendall(f"{i:02d};".encode())
                time.sleep(0.002)
            received = b""
            while len(received) < 60:
                received += conn.recv(4096)
            elapsed_ms = (time.perf_counter() - start) * 1000
    listener.close()
    assert received.decode() == "".join(f"{i:02d};" for i in range(20))
    assert elapsed_ms >= 2 * (profile.delay_ms - profile.jitter_ms)
