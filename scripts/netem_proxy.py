"""TCP proxy that adds realistic network delay, jitter and loss spikes (a portable stand-in for
Linux `tc netem`, which is not available on Windows dev machines).

Every chunk in each direction is held for `delay ± jitter` ms; with probability `spike_chance` it
is held `spike_ms` longer (what a TCP retransmission after packet loss looks like to the app).
Order is preserved per direction, as TCP would, so a slow chunk also delays the ones behind it.

Usage from code:
    with NetemProxy("127.0.0.1", 8000, PROFILES["wifi"]) as proxy:
        ws_connect(f"ws://{proxy.address}/rooms/...")
"""

import asyncio
import ctypes
import random
import sys
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    delay_ms: float  # one-way base delay
    jitter_ms: float  # one-way, uniform +/- around the base
    spike_chance: float = 0.0
    spike_ms: float = 0.0

    @property
    def rtt_label(self) -> str:
        return f"RTT ~{2 * self.delay_ms:.0f}+/-{2 * self.jitter_ms:.0f} ms"


PROFILES = {
    "lan": Profile("lan", delay_ms=1, jitter_ms=0.5),
    "wifi": Profile("wifi", delay_ms=10, jitter_ms=5, spike_chance=0.005, spike_ms=60),
    "4g": Profile("4g", delay_ms=30, jitter_ms=15, spike_chance=0.01, spike_ms=120),
    "poor": Profile("poor", delay_ms=75, jitter_ms=40, spike_chance=0.03, spike_ms=250),
}


class NetemProxy:
    def __init__(self, target_host: str, target_port: int, profile: Profile, seed: int | None = None):
        self.target = (target_host, target_port)
        self.profile = profile
        self.rng = random.Random(seed)
        self.port = 0
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._server: asyncio.base_events.Server | None = None

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    def _hold_seconds(self) -> float:
        p = self.profile
        ms = max(0.0, p.delay_ms + self.rng.uniform(-p.jitter_ms, p.jitter_ms))
        if p.spike_chance and self.rng.random() < p.spike_chance:
            ms += p.spike_ms
        return ms / 1000

    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        queue: asyncio.Queue = asyncio.Queue()

        async def deliver():
            while True:
                due, data = await queue.get()
                if data is None:
                    break
                wait = due - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                writer.write(data)
                await writer.drain()
            writer.close()

        sender = asyncio.ensure_future(deliver())
        last_due = 0.0
        try:
            while data := await reader.read(65536):
                last_due = max(last_due, time.monotonic() + self._hold_seconds())
                queue.put_nowait((last_due, data))
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            queue.put_nowait((0.0, None))
            try:
                await sender
            except ConnectionError:
                pass

    async def _handle(self, client_reader, client_writer) -> None:
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(*self.target)
        except OSError:
            client_writer.close()
            return
        await asyncio.gather(
            self._pipe(client_reader, upstream_writer),
            self._pipe(upstream_reader, client_writer),
            return_exceptions=True,
        )

    def start(self) -> "NetemProxy":
        if sys.platform == "win32":
            # Default Windows timer granularity (~15.6 ms) would swamp the LAN/Wi-Fi delays.
            ctypes.windll.winmm.timeBeginPeriod(1)
        self._thread.start()

        async def listen():
            self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
            self.port = self._server.sockets[0].getsockname()[1]

        asyncio.run_coroutine_threadsafe(listen(), self._loop).result(timeout=5)
        return self

    def stop(self) -> None:
        async def shutdown():
            if self._server is not None:
                self._server.close()
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()

        asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(timeout=5)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if sys.platform == "win32":
            ctypes.windll.winmm.timeEndPeriod(1)

    def __enter__(self) -> "NetemProxy":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
