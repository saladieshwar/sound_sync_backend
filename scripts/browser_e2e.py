"""Phase 6 QA: cross-stack end-to-end run in real browsers (headless Edge/Chrome over CDP).

Two isolated browser profiles (two "devices") go through the whole product against the real
frontend, API, WebSocket server and database, and the listener's real <audio> is checked against
the controller's while a song plays. Finally one user is promoted to admin (directly in the DB)
and uploads, lists and deletes a song through the Admin Panel.

Run from backend/ with the API and the frontend running:

    python -m scripts.browser_e2e [app_url] [api_url]

Defaults: http://localhost:5173 and http://localhost:8000. The API's CORS_ORIGINS must allow
app_url. Requires seeded songs (`python -m scripts.seed`). Set BROWSER_PATH to use a browser other
than Microsoft Edge. Throwaway users are deleted at the end.
"""

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
import wave

import httpx
from sqlalchemy import delete, update
from websockets.sync.client import connect as ws_connect

from app.db.session import SessionLocal
from app.models import User

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9333
PASSWORD = "browser-e2e-pass"
TOKEN_KEY = "soundsync_token"

SETTLE_SECONDS = 3.0  # after play/join: the player's settle jumps finish within ~2 s
SAMPLES = 25
SAMPLE_EVERY = 0.3
MAX_DRIFT_SECONDS = 0.15  # frontend RESYNC_SECONDS: beyond this the listener would re-jump
MAX_SEEKS_WHILE_SETTLED = 1  # a settled player must not keep correcting (that is audible)

# Wraps window.Audio so the test can read the real media element the player creates.
INSTRUMENT = """
(() => {
  const Original = window.Audio
  window.__audios = []
  window.Audio = function (...args) {
    const el = new Original(...args)
    el.__seeks = 0
    el.__stalls = 0
    el.addEventListener('seeking', () => (el.__seeks += 1))
    el.addEventListener('waiting', () => (el.__stalls += 1))
    window.__audios.push(el)
    return el
  }
  window.Audio.prototype = Original.prototype
})()
"""

AUDIO_STATE = """
(() => {
  const a = window.__audios?.at(-1)
  return a ? { t: Date.now(), pos: a.currentTime, paused: a.paused, src: a.src,
               seeks: a.__seeks, stalls: a.__stalls, ready: a.readyState } : null
})()
"""


class Browser:
    def __init__(self, path: str):
        self.profile_dir = tempfile.mkdtemp(prefix="soundsync-e2e-")
        self.proc = subprocess.Popen(
            [
                path,
                "--headless=new",
                f"--remote-debugging-port={DEBUG_PORT}",
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--autoplay-policy=no-user-gesture-required",
                # Each simulated device is a foreground tab on its own phone/laptop.
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        while True:
            try:
                info = httpx.get(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=1).json()
                break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise SystemExit("Browser did not start (set BROWSER_PATH?)")
                time.sleep(0.25)
        self._ws_ctx = ws_connect(info["webSocketDebuggerUrl"], max_size=None, open_timeout=10)
        self.ws = self._ws_ctx.__enter__()
        self.next_id = 0

    def call(self, method: str, session: str | None = None, **params):
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        self.ws.send(json.dumps(message))
        while True:
            reply = json.loads(self.ws.recv(timeout=30))
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    def new_device(self, name: str) -> "Device":
        context = self.call("Target.createBrowserContext")["browserContextId"]
        target = self.call("Target.createTarget", url="about:blank", browserContextId=context)
        session = self.call("Target.attachToTarget", targetId=target["targetId"], flatten=True)
        device = Device(self, session["sessionId"], name)
        self.call("Page.enable", device.session)
        self.call("Page.addScriptToEvaluateOnNewDocument", device.session, source=INSTRUMENT)
        return device

    def close(self) -> None:
        try:
            self.call("Browser.close")
        except Exception:
            pass
        try:
            self._ws_ctx.__exit__(None, None, None)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile_dir, ignore_errors=True)


class Device:
    def __init__(self, browser: Browser, session: str, name: str):
        self.browser = browser
        self.session = session
        self.name = name

    def eval(self, expression: str):
        result = self.browser.call(
            "Runtime.evaluate", self.session, expression=expression, awaitPromise=True, returnByValue=True
        )
        if "exceptionDetails" in result:
            raise RuntimeError(f"{self.name}: {result['exceptionDetails']}")
        return result["result"].get("value")

    def goto(self, url: str) -> None:
        self.browser.call("Page.navigate", self.session, url=url)
        self.wait("document.readyState === 'complete'")

    def wait(self, expression: str, timeout: float = 10.0, label: str | None = None) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            try:
                ok = self.eval(f"!!({expression})")
            except RuntimeError:
                ok = False
            if ok:
                return True
            if time.monotonic() > deadline:
                raise AssertionError(f"{self.name}: timed out waiting for {label or expression}")
            time.sleep(0.1)

    def path(self) -> str:
        return self.eval("location.pathname")

    def fill(self, testid: str, value: str) -> None:
        self.eval(
            f"""(() => {{
              const el = document.querySelector('[data-testid="{testid}"]')
              const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
              setter.call(el, {json.dumps(value)})
              el.dispatchEvent(new Event('input', {{ bubbles: true }}))
            }})()"""
        )

    def click(self, selector: str) -> None:
        self.wait(f"document.querySelector({json.dumps(selector)})", label=selector)
        self.eval(f"document.querySelector({json.dumps(selector)}).click()")

    def text(self, testid: str) -> str:
        return self.eval(f"document.querySelector('[data-testid=\"{testid}\"]')?.textContent ?? ''")

    def audio(self) -> dict | None:
        return self.eval(AUDIO_STATE)

    def token(self) -> str:
        return self.eval(f"localStorage.getItem('{TOKEN_KEY}')")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{f' - {detail}' if detail else ''}")
    if not ok:
        raise SystemExit(1)


def register(device: Device, app: str, name: str, emails: list[str]) -> None:
    email = f"e2e_{name}_{uuid.uuid4().hex[:8]}@soundsync.dev"
    emails.append(email)
    device.goto(f"{app}/register")
    device.wait("document.querySelector('[data-testid=\"register-submit\"]')")
    device.fill("register-username", name)
    device.fill("register-email", email)
    device.fill("register-password", PASSWORD)
    device.click('[data-testid="register-submit"]')
    device.wait("location.pathname === '/'", label="home after register")


def drift_samples(controller: Device, listener: Device) -> tuple[list[float], int]:
    """Listener minus controller audio position at the same instant, plus listener seeks meanwhile."""
    drifts = []
    start_seeks = listener.audio()["seeks"]
    for _ in range(SAMPLES):
        a, b = controller.audio(), listener.audio()
        if not (a["paused"] or b["paused"]):
            drifts.append((b["pos"] - b["t"] / 1000) - (a["pos"] - a["t"] / 1000))
        time.sleep(SAMPLE_EVERY)
    return drifts, listener.audio()["seeks"] - start_seeks


def same_song_playing(device: Device, src_part: str = "") -> str:
    return (
        f"(() => {{ const a = window.__audios?.at(-1); return a && !a.paused && a.currentTime > 0.5 "
        f"&& a.src.includes({json.dumps(src_part)}) }})()"
    )


def report_sync(label: str, controller: Device, listener: Device) -> dict:
    time.sleep(SETTLE_SECONDS)
    drifts, seeks = drift_samples(controller, listener)
    abs_ms = sorted(abs(d) * 1000 for d in drifts)
    stats = {
        "samples": len(drifts),
        "median_ms": statistics.median(abs_ms),
        "p95_ms": abs_ms[max(0, int(len(abs_ms) * 0.95) - 1)],
        "max_ms": abs_ms[-1],
        "seeks": seeks,
    }
    check(
        f"{label}: listener audio in sync with controller",
        len(drifts) >= SAMPLES - 2 and stats["max_ms"] <= MAX_DRIFT_SECONDS * 1000,
        f"|drift| median {stats['median_ms']:.0f} ms, p95 {stats['p95_ms']:.0f} ms, "
        f"max {stats['max_ms']:.0f} ms over {stats['samples']} samples",
    )
    check(f"{label}: no correction storm", seeks <= MAX_SEEKS_WHILE_SETTLED, f"{seeks} seek(s) while settled")
    return stats


def status_text(prefix: str) -> str:
    return (
        "[...document.querySelectorAll('[role=\"status\"]')]"
        f".some((el) => el.textContent.startsWith({json.dumps(prefix)}))"
    )


def _write_wav(path: str, seconds: int = 2) -> None:
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(8000)
        wav.writeframes(bytes([128]) * 8000 * seconds)


def admin_flow(device: Device, app: str, api: str, email: str, bob_email: str) -> None:
    """ADM-01/04/05 in a real browser: upload through the file picker, list users/rooms, delete."""
    print("Admin")
    with SessionLocal() as db:
        db.execute(update(User).where(User.email == email).values(is_admin=True))
        db.commit()
    device.goto(f"{app}/admin")
    device.wait("document.querySelector('[role=\"tab\"]')", label="admin panel")
    check("promoted user opens the Admin Panel", device.path() == "/admin")

    title = f"E2E Upload {uuid.uuid4().hex[:6]}"
    wav_dir = tempfile.mkdtemp(prefix="soundsync-e2e-wav-")
    wav_path = os.path.join(wav_dir, "e2e-upload.wav")
    _write_wav(wav_path)
    try:
        for selector, value in (
            ('input[name="title"]', title),
            ('input[name="artist"]', "E2E Artist"),
            ('input[name="category"]', "e2e"),
            ('input[name="duration_seconds"]', "2"),
        ):
            device.eval(
                f"""(() => {{
                  const el = document.querySelector({json.dumps(selector)})
                  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, {json.dumps(value)})
                  el.dispatchEvent(new Event('input', {{ bubbles: true }}))
                }})()"""
            )
        root = device.browser.call("DOM.getDocument", device.session)["root"]["nodeId"]
        node = device.browser.call(
            "DOM.querySelector", device.session, nodeId=root, selector='input[name="audio_file"]'
        )["nodeId"]
        device.browser.call("DOM.setFileInputFiles", device.session, nodeId=node, files=[wav_path])
        device.eval("document.querySelector('input[name=title]').form.requestSubmit()")
        device.wait(
            status_text('Uploaded'), label="upload"
        )
    finally:
        shutil.rmtree(wav_dir, ignore_errors=True)
    found = httpx.get(f"{api}/songs/search", params={"q": title}).json()
    check("uploaded song is searchable", [s["title"] for s in found] == [title])
    song = found[0]
    served = httpx.get(f"{api}{song['audio_url']}")
    check("uploaded audio is served under /media", served.status_code == 200 and served.content[:4] == b"RIFF")

    device.click('[role="tab"]:nth-child(3)')
    device.wait(f"document.body.textContent.includes({json.dumps(bob_email)})", label="users table")
    check("Users tab lists registered users", True)
    device.click('[role="tab"]:nth-child(4)')
    device.wait("document.body.textContent.includes('Room ID') || document.body.textContent.includes('No active rooms')")
    check("Rooms tab lists active rooms (closed E2E room not shown)", "E2E Friday mix" not in device.eval("document.body.textContent"))

    device.click('[role="tab"]:nth-child(2)')
    device.eval("window.confirm = () => true")
    device.click(f'button[aria-label={json.dumps("Delete " + title)}]')
    device.wait(status_text('Deleted'), label="delete")
    gone = httpx.get(f"{api}/songs/{song['id']}").status_code == 404
    file_gone = httpx.get(f"{api}{song['audio_url']}").status_code == 404
    check("deleting removes the song and its audio file", gone and file_gone)


def main() -> None:
    app = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173").rstrip("/")
    api = (sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000").rstrip("/")
    emails: list[str] = []
    browser = Browser(os.environ.get("BROWSER_PATH", EDGE))
    started = time.monotonic()
    try:
        alice, bob = browser.new_device("alice"), browser.new_device("bob")

        print("Auth")
        alice.goto(f"{app}/")
        alice.wait("location.pathname === '/login'", label="redirect to /login")
        check("anonymous visitor is sent to /login", True)
        register(alice, app, "alice", emails)
        register(bob, app, "bob", emails)
        check("both users registered and landed on Home", alice.path() == bob.path() == "/")
        alice_api = httpx.Client(base_url=api, headers={"Authorization": f"Bearer {alice.token()}"})
        bob_api = httpx.Client(base_url=api, headers={"Authorization": f"Bearer {bob.token()}"})
        bob_id = bob_api.get("/auth/me").json()["id"]

        print("Browse and play")
        first_song = '[aria-label="All Songs"] [data-testid^="song-row-"] button'
        alice.wait(f"document.querySelector('{first_song}')", label="All Songs list")
        title = alice.eval(f"document.querySelector('{first_song} p').textContent")
        alice.click(first_song)
        alice.wait(same_song_playing(alice), label="solo playback")
        check(f"'{title}' plays through the real <audio>", True)
        alice.wait(
            f"document.querySelector('[aria-label=\"Recently Played\"]')?.textContent.includes({json.dumps(title)})"
        )
        check("play is logged to Recently Played", True)
        alice.click('[data-testid="player-like"]')
        alice.wait(
            f"document.querySelector('[aria-label=\"Liked Songs\"]')?.textContent.includes({json.dumps(title)})"
        )
        liked = [x["song"]["title"] for x in alice_api.get("/users/me/liked-songs").json()]
        check("like is saved", liked == [title])

        alice.fill("navbar-search", title[:4])
        alice.eval("document.querySelector('form[role=\"search\"]').requestSubmit()")
        alice.wait("location.pathname === '/search'")
        alice.wait(f"document.body.textContent.includes('Results for')")
        check("navbar search shows results", title in alice.eval("document.body.textContent"))

        print("Musical Room")
        alice.click('a[aria-label="Musical Room"]')
        alice.wait("document.querySelector('[data-testid=\"room-create-name\"]')")
        alice.fill("room-create-name", "E2E Friday mix")
        alice.click('[data-testid="room-create-submit"]')
        alice.wait("location.pathname.startsWith('/room/')", label="room page")
        alice.wait("document.querySelector('[data-testid=\"room-id\"]')?.textContent.length === 8")
        room_id = alice.text("room-id")
        alice.wait("document.querySelector('[data-testid=\"socket-status\"]')?.textContent === 'Live'")
        check(f"room {room_id} created and live", len(room_id) == 8)
        check(
            "entering an empty room stops solo playback",
            bool(alice.wait("window.__audios.at(-1).paused")),
        )

        link = alice.eval("document.querySelector('[data-testid=\"room-join-link\"]').value")
        bob.goto(link.replace(room_id, room_id.lower()))
        bob.click('[data-testid="room-join-confirm"]')
        bob.wait("document.querySelector('[data-testid=\"socket-status\"]')?.textContent === 'Live'")
        alice.wait(f"document.querySelector('[data-testid=\"participant-{bob_id}\"]')")
        check("second device joined via the join link and is visible to the admin", True)

        print("Playback sync")
        alice.click('[data-testid="room-song-picker"] li:nth-child(1) button')
        alice.wait(same_song_playing(alice), label="controller playing")
        src = alice.audio()["src"].rsplit("/", 1)[-1]
        bob.wait(same_song_playing(bob, src), timeout=10, label="listener playing same song")
        check("song_change reaches the listener", True, src)
        play_stats = report_sync("after song_change", alice, bob)

        alice.click('[data-testid="room-toggle"]')
        for device in (alice, bob):
            device.wait("window.__audios.at(-1).paused", timeout=3, label="paused")
        a, b = alice.audio(), bob.audio()
        check("pause stops both devices at the same spot", abs(a["pos"] - b["pos"]) <= 0.05,
              f"{abs(a['pos'] - b['pos']) * 1000:.0f} ms apart")
        alice.click('[data-testid="room-toggle"]')
        for device in (alice, bob):
            device.wait(same_song_playing(device, src), timeout=5, label="resumed")
        resume_stats = report_sync("after resume", alice, bob)

        print("Control transfer")
        alice.click(f'[data-testid="transfer-{bob_id}"]')
        bob.wait("document.querySelector('[data-testid=\"room-controller\"]')?.textContent.startsWith('You control')")
        check("bob now controls playback", True)
        bob.click('[data-testid="room-song-picker"] li:nth-child(2) button')
        bob.wait("window.__audios.at(-1).src !== " + json.dumps(alice.audio()["src"]), label="new song")
        new_src = bob.audio()["src"].rsplit("/", 1)[-1]
        bob.wait(same_song_playing(bob, new_src))
        alice.wait(same_song_playing(alice, new_src), label="admin follows new controller")
        check("new controller's song plays on the admin's device", True, new_src)
        transfer_stats = report_sync("after transfer", bob, alice)

        print("Leave")
        bob.click('[data-testid="leave-room"]')
        bob.wait("location.pathname === '/room'")
        bob.wait("window.__audios.at(-1).paused")
        alice.wait(f"!document.querySelector('[data-testid=\"participant-{bob_id}\"]')")
        alice.wait("document.querySelector('[data-testid=\"room-controller\"]')?.textContent.startsWith('You control')")
        check("participant leaves; control returns to the admin", True)
        alice.click('[data-testid="leave-room"]')
        alice.wait("location.pathname === '/room'")
        check("admin leaving closes the room", alice_api.get(f"/rooms/{room_id}").status_code == 410)

        alice.click('a[href="/"]')
        alice.wait(f"document.querySelector('{first_song}')")
        alice.click(first_song)
        alice.wait(same_song_playing(alice), label="solo playback after room")
        check("solo playback works again after leaving", True)
        check("still the same session (never sent back to login)", alice.token() and bob.token())

        admin_flow(alice, app, api, emails[0], bob_email=emails[1])

        print(f"\nAll browser E2E checks passed in {time.monotonic() - started:.0f}s.")
        for label, s in (("song_change", play_stats), ("resume", resume_stats), ("transfer", transfer_stats)):
            print(f"  sync {label:12} median {s['median_ms']:5.0f} ms  p95 {s['p95_ms']:5.0f} ms  "
                  f"max {s['max_ms']:5.0f} ms  seeks {s['seeks']}")
    finally:
        browser.close()
        if emails:
            with SessionLocal() as db:
                db.execute(delete(User).where(User.email.in_(emails)))
                db.commit()


if __name__ == "__main__":
    main()
