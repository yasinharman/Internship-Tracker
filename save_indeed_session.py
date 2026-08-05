"""
LOG INTO INDEED BY HAND, SAVE THE WHOLE SESSION - NOT JUST THE COOKIES
========================================================================

INDEED_COOKIES_B64 (session_cookies.py) captures one thing: the Cookie
header a browser would send. MEASURED 05.08.2026: a Google/OAuth-linked
account signed in that way gets page 1 of every search through Playwright
with no block at all, then a sign-in wall on page 2 - every time, every
search, in the same run that proved Cloudflare itself was no longer the
problem (see playwright_middleware.py, indeed_cards.py). One explanation
that fits: a Google login can leave state in the browser's localStorage /
sessionStorage that a plain Cookie header never carries, and Indeed's own
page-two check reads more than cookies.

`BrowserContext.storage_state()` saves all three - cookies, localStorage,
sessionStorage - in one file. This script exists to produce that file by
doing the one part that cannot be scripted: signing in, by hand, in a
window you can actually see and click "Continue with Google" in.

USAGE
-----
    python save_indeed_session.py

A visible (headful - this needs a real display) Chromium window opens on
tr.indeed.com. Sign in normally, Google button included, at your own pace -
this script does not wait for a keypress, it polls for the same cookies
IndeedCardsSpider itself treats as "signed in" (SIGNED_IN_COOKIES /
OAUTH_SIGNED_IN_COOKIES below - keep these two in sync with indeed_cards.py)
and saves the moment they appear, then closes the window on its own.

FIRST ATTEMPT 05.08.2026 FAILED AT THE GOOGLE STEP, NOT THE INDEED STEP
--------------------------------------------------------------------------
Google refused the sign-in outright ("Bu tarayici veya uygulama guvenli
olmayabilir") - a deliberate Google policy against OAuth inside an
automation-flagged browser (navigator.webdriver=true and friends), nothing
to do with Cloudflare or Indeed. Fixed here by launching the REAL installed
Brave binary (BRAVE_PATH below) instead of Playwright's bundled Chromium,
plus --disable-blink-features=AutomationControlled and an init script that
hides navigator.webdriver before any page's JS runs. Standard, well-known
combination for this specific Google block.

Point PlaywrightMiddleware at the result with:
    INDEED_STORAGE_STATE=/absolute/path/to/indeed-storage-state.json

Absolute, not relative: main.py runs the spider with
cwd=MultiwebsiteScraper, so a relative path resolves against the wrong
directory - the same trap INDEED_COOKIES (a path form) already warns about
in session_cookies.py.

THIS FILE IS THE ACCOUNT, SAME AS THE COOKIE EXPORT IT REPLACES
-----------------------------------------------------------------
Gitignored (see .gitignore: indeed-storage-state.json). Never commit it,
never paste its contents anywhere. Re-run this script whenever the session
in use expires - the spider says so explicitly when that happens (see
IndeedCardsSpider.note_sign_in_wall).
"""

import os
import time

from playwright.sync_api import sync_playwright

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "indeed-storage-state.json")

# The actually-installed browser, not Playwright's bundled Chromium build -
# see the module docstring for why that matters to Google specifically.
BRAVE_PATH = "/opt/brave.com/brave/brave"

HIDE_WEBDRIVER_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)

SIGNED_IN_MARKERS = (
    ("SOCK", "SHOE"),
    ("__Secure-PassportAuthProxy-RefreshToken", "JSESSIONID"),
)
TIMEOUT_SECONDS = 300
POLL_SECONDS = 2


def _signed_in(cookies):
    names = {c["name"] for c in cookies}
    return any(all(name in names for name in group) for group in SIGNED_IN_MARKERS)


def main():
    with sync_playwright() as p:
        launch_kwargs = {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if os.path.isfile(BRAVE_PATH):
            launch_kwargs["executable_path"] = BRAVE_PATH
        else:
            print(f"({BRAVE_PATH} not found, falling back to bundled Chromium)")
        browser = p.chromium.launch(**launch_kwargs)

        context = browser.new_context(
            locale="tr-TR", viewport={"width": 1280, "height": 800},
        )
        context.add_init_script(HIDE_WEBDRIVER_SCRIPT)
        page = context.new_page()
        page.goto("https://tr.indeed.com/")

        print(
            "Tarayici penceresi acildi. tr.indeed.com uzerinden NORMAL "
            "sekilde giris yap ('Continue with Google' dahil), kendi hizinda.\n"
            f"Giris otomatik algilanacak (en fazla {TIMEOUT_SECONDS}s bekleniyor)."
        )

        waited = 0
        while waited < TIMEOUT_SECONDS:
            if _signed_in(context.cookies()):
                break
            time.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
        else:
            browser.close()
            print(
                f"{TIMEOUT_SECONDS}s icinde giris algilanamadi - pencere "
                f"kapatildi, hicbir sey kaydedilmedi. Tekrar calistir."
            )
            return

        context.storage_state(path=OUTPUT_PATH)
        cookie_count = len(context.cookies())
        browser.close()

    print(f"Kaydedildi: {OUTPUT_PATH} ({cookie_count} cookie dahil)")
    print(
        "Simdi .env icine ekle: INDEED_STORAGE_STATE=" + OUTPUT_PATH +
        "\n(INDEED_COOKIES_B64'u silmene gerek yok - storage_state varsa "
        "PlaywrightMiddleware onu once okur, ama pagination'in "
        "'anonim degilim' kontrolu hala INDEED_COOKIES_B64'e bakiyor.)"
    )


if __name__ == "__main__":
    main()
