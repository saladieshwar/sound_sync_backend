"""Phase 8 FE: UI/UX check of every main screen at phone, tablet and desktop size (headless Edge).

One user registers, is promoted to admin, plays a song, opens a Musical Room with a song playing,
and opens each Admin tab. Every screen is checked at each viewport for:

* no horizontal overflow: nothing sticks out past the right edge (wide tables must scroll inside
  their own box), so the page never scrolls sideways on a phone;
* the footer player never covers content: the last item on the page can be scrolled above it;
* every button, link and form field has an accessible name (screen readers, voice control);
* every button and slider is at least 24 x 24 px (WCAG 2.2 target size);
* no uncaught script errors.

Screenshots go to docs/qa/ux/ (one JPEG per screen and viewport). Run from backend/ with the API
and the frontend running and the seed loaded:

    python -m scripts.ux_check [app_url] [api_url]

Defaults: http://localhost:5173 and http://localhost:8000. The throwaway user is deleted at the end.
"""

import base64
import os
import sys
import time
from pathlib import Path

from sqlalchemy import delete, update

from app.db.session import SessionLocal
from app.models import User
from scripts.browser_e2e import EDGE, Browser, Device, register

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "qa" / "ux"
VIEWPORTS = {"phone": (360, 740), "tablet": (768, 1024), "desktop": (1366, 768)}
MIN_TARGET_PX = 24

ERROR_TRAP = """
window.__errors = []
addEventListener('error', (e) => window.__errors.push(String(e.message)))
addEventListener('unhandledrejection', (e) => window.__errors.push(String(e.reason)))
"""

# Returns a list of problems on the current screen (empty = pass).
CHECKS = """
(() => {
  const problems = []
  const vw = document.documentElement.clientWidth
  const visible = (el) => {
    const r = el.getBoundingClientRect()
    const s = getComputedStyle(el)
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
  }
  // Inside its own scroll box (wide tables) or deliberately clipped (truncated text with "…").
  // <main> does not count: anything it clips is content the user can never reach.
  const contained = (el) => {
    for (let p = el.parentElement; p && p.tagName !== 'MAIN' && p.id !== 'root'; p = p.parentElement) {
      if (getComputedStyle(p).overflowX !== 'visible') return true
    }
    return false
  }
  const describe = (el) =>
    el.tagName.toLowerCase() + (el.dataset.testid ? `[${el.dataset.testid}]` : '') +
    ` "${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30)}"`

  if (document.documentElement.scrollWidth > vw + 1) problems.push(`page scrolls sideways (${document.documentElement.scrollWidth} > ${vw})`)
  for (const el of document.querySelectorAll('main *, header *, footer *')) {
    if (!visible(el) || contained(el)) continue
    const r = el.getBoundingClientRect()
    if (r.right > vw + 1 || r.left < -1) { problems.push(`overflows the screen: ${describe(el)}`); break }
  }

  const main = document.querySelector('main')
  const footer = document.querySelector('footer[aria-label="Player"]')
  if (main && footer) {
    main.scrollTop = main.scrollHeight
    const items = [...main.querySelectorAll('*')].filter(visible)
    const bottom = Math.max(...items.map((el) => el.getBoundingClientRect().bottom))
    const top = footer.getBoundingClientRect().top
    if (bottom > top + 1) problems.push(`footer player covers the last ${Math.round(bottom - top)} px of content`)
    main.scrollTop = 0
  }

  const named = (el) =>
    (el.getAttribute('aria-label') || '').trim() ||
    (el.getAttribute('aria-labelledby') && document.getElementById(el.getAttribute('aria-labelledby'))?.textContent.trim()) ||
    (el.labels && [...el.labels].some((l) => l.textContent.trim())) ||
    (el.tagName !== 'INPUT' && el.textContent.trim()) ||
    (el.getAttribute('title') || '').trim()
  for (const el of document.querySelectorAll('button, a[href], input, select, textarea')) {
    if (!visible(el) || el.type === 'hidden') continue
    if (!named(el)) problems.push(`no accessible name: ${describe(el)}`)
  }
  for (const el of document.querySelectorAll('button, input[type="range"]')) {
    if (!visible(el)) continue
    const r = el.getBoundingClientRect()
    if (r.width < 24 || r.height < 24) problems.push(`target smaller than 24 px (${Math.round(r.width)}x${Math.round(r.height)}): ${describe(el)}`)
  }
  for (const e of window.__errors || []) problems.push(`script error: ${e}`)
  return problems
})()
"""


# Screenshots are committed: rows from real accounts on the dev database must not appear in them.
MASK_PEOPLE = """
for (const row of document.querySelectorAll('tbody tr')) {
  const [, name, email] = row.cells
  if (email && !email.textContent.trim().endsWith('@soundsync.dev')) {
    name.textContent = 'user'
    email.textContent = 'user@example.com'
  }
}
"""
MASK_ROOMS = """
for (const row of document.querySelectorAll('tbody tr')) {
  if (!row.cells[1].textContent.startsWith('UX check')) row.cells[1].textContent = 'Another room'
}
"""


def set_viewport(device: Device, width: int, height: int) -> None:
    device.browser.call(
        "Emulation.setDeviceMetricsOverride",
        device.session,
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=width < 768,
    )
    time.sleep(0.5)  # let the layout settle after the resize


def capture(device: Device, screen: str, results: list[tuple[str, str, list[str]]], mask: str = "") -> None:
    for name, (width, height) in VIEWPORTS.items():
        set_viewport(device, width, height)
        problems = device.eval(CHECKS)
        if mask:
            device.eval(mask)
        shot = device.browser.call("Page.captureScreenshot", device.session, format="jpeg", quality=70)
        (OUT_DIR / f"{screen}-{name}.jpg").write_bytes(base64.b64decode(shot["data"]))
        results.append((screen, name, problems))
        status = "PASS" if not problems else "FAIL"
        print(f"  [{status}] {screen:14} {name:8} {width}x{height}" + "".join(f"\n      - {p}" for p in problems))
    set_viewport(device, *VIEWPORTS["desktop"])


def main() -> int:
    app = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173").rstrip("/")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    emails: list[str] = []
    results: list[tuple[str, str, list[str]]] = []
    browser = Browser(os.environ.get("BROWSER_PATH", EDGE))
    try:
        device = browser.new_device("ux")
        browser.call("Page.addScriptToEvaluateOnNewDocument", device.session, source=ERROR_TRAP)
        set_viewport(device, *VIEWPORTS["desktop"])

        device.goto(f"{app}/login")
        device.wait("document.querySelector('[data-testid=\"login-submit\"]')", label="login form")
        capture(device, "login", results)
        device.click('a[href="/register"]')
        device.wait("document.querySelector('[data-testid=\"register-submit\"]')", label="register form")
        capture(device, "register", results)

        register(device, app, "uxcheck", emails)
        with SessionLocal() as db:
            db.execute(update(User).where(User.email == emails[0]).values(is_admin=True))
            db.commit()
        device.goto(f"{app}/")  # reload so the app sees the admin role
        first_song = '[aria-label="All Songs"] [data-testid^="song-row-"] button'
        device.wait(f"document.querySelector('{first_song}')", label="All Songs list")
        device.click(first_song)
        device.wait("window.__audios?.at(-1)?.currentTime > 0.3", label="playback")
        device.wait("document.querySelector('[aria-label=\"Recently Played\"] [data-testid^=\"song-row-\"]')")
        capture(device, "home", results)

        device.click('[data-testid="player-title"]')
        device.wait("location.pathname === '/now-playing'")
        capture(device, "now-playing", results)

        device.click('a[aria-label="Musical Room"]')
        device.wait("document.querySelector('[data-testid=\"room-create-name\"]')")
        capture(device, "room-landing", results)

        device.fill("room-create-name", "UX check room with a fairly long name")
        device.click('[data-testid="room-create-submit"]')
        device.wait("document.querySelector('[data-testid=\"socket-status\"]')?.textContent === 'Live'")
        device.click('[data-testid="room-song-picker"] li:nth-child(1) button')
        device.wait("window.__audios?.at(-1) && !window.__audios.at(-1).paused", label="room playback")
        capture(device, "room", results)

        device.click('a[href="/admin"]')
        device.wait("document.querySelector('[role=\"tab\"]')", label="admin panel")
        for index, screen in enumerate(("admin-upload", "admin-songs", "admin-users", "admin-rooms"), 1):
            device.click(f'[role="tab"]:nth-child({index})')
            device.wait(
                "!document.body.textContent.includes('Loading…') || document.querySelector('form')",
                label=screen,
            )
            capture(device, screen, results, {"admin-users": MASK_PEOPLE, "admin-rooms": MASK_ROOMS}.get(screen, ""))
    finally:
        browser.close()
        if emails:
            with SessionLocal() as db:
                db.execute(delete(User).where(User.email.in_(emails)))
                db.commit()

    failed = [r for r in results if r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} screen x viewport checks passed. Screenshots: {OUT_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
