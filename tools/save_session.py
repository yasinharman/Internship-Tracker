"""
LOG INTO A JOB BOARD BY HAND, SAVE THE WHOLE SESSION - NOT JUST THE COOKIES
============================================================================

    python -m tools.save_session indeed
    python -m tools.save_session linkedin

The cookie-only export (`<SITE>_COOKIES_B64`, see session_cookies.py) captures
one thing: the Cookie header a browser would send. MEASURED 05.08.2026 on
Indeed: a Google/OAuth-linked account signed in that way gets page 1 of every
search through Playwright with no block at all, then a sign-in wall on page 2 -
every time, every search, in the same run that proved Cloudflare itself was no
longer the problem (see playwright_middleware.py, indeed_cards.py). One
explanation that fits: a Google login can leave state in the browser's
localStorage / sessionStorage that a plain Cookie header never carries, and the
site's own page-two check reads more than cookies.

`BrowserContext.storage_state()` saves all three - cookies, localStorage,
sessionStorage - in one file. This script exists to produce that file by doing
the one part that cannot be scripted: signing in, by hand, in a window you can
actually see and click "Continue with Google" in.

ONE SCRIPT, ONE PROFILE PER SITE
--------------------------------
It was `save_indeed_session.py` until LinkedIn arrived. Everything that made it
work - the real Brave binary, the automation flags, the polling - is site
independent; only the address to open, the cookies that mean "signed in" and
the file to write differ. Those three live in SITES below, and they are the
whole of what a new site has to add here.

FIRST ATTEMPT 05.08.2026 FAILED AT THE GOOGLE STEP, NOT THE INDEED STEP
--------------------------------------------------------------------------
Google refused the sign-in outright ("Bu tarayici veya uygulama guvenli
olmayabilir") - a deliberate Google policy against OAuth inside an
automation-flagged browser (navigator.webdriver=true and friends), nothing to
do with Cloudflare or the job board. Fixed here by launching the REAL installed
Brave binary (BRAVE_PATH below) instead of Playwright's bundled Chromium, plus
--disable-blink-features=AutomationControlled and an init script that hides
navigator.webdriver before any page's JS runs. Standard, well-known combination
for this specific Google block. It matters for LinkedIn too, which offers the
same Google button.

THESE FILES ARE THE ACCOUNTS
----------------------------
Gitignored, one line per site. Never commit one, never paste its contents
anywhere. Re-run this script whenever a session expires - the spiders say so
explicitly when that happens (see IndeedCardsSpider.note_sign_in_wall).
"""

import os
import sys
import time

from playwright.sync_api import sync_playwright

# The REPOSITORY ROOT, not this file's directory. The session files belong
# next to .env, which is what LINKEDIN_STORAGE_STATE / INDEED_STORAGE_STATE
# point at and what .gitignore names. This script moved into tools/ on
# 27.08.2026; dirname(__file__) would now write tools/linkedin-storage-state.json
# while .env still read the old path, and the crawl would go on using a stale
# session while this printed "saved" - no error anywhere.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The actually-installed browser, not Playwright's bundled Chromium build -
# see the module docstring for why that matters to Google specifically.
BRAVE_PATH = "/opt/brave.com/brave/brave"

HIDE_WEBDRIVER_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)

TIMEOUT_SECONDS = 300
POLL_SECONDS = 2


###################################################################
# WHAT EACH SITE NEEDS - THE ONLY PART THAT VARIES                #
###################################################################
'''
    `signed_in` is a list of cookie GROUPS, and the login counts as done when
    every name in ANY ONE group is present. Groups exist because one site can
    hand out different cookies depending on how you signed in: an Indeed
    account with a password gets SOCK/SHOE, while a Google-linked one never
    does and carries the __Secure-PassportAuthProxy-* family instead
    (discovered 03.08.2026).

    Keep these in sync with the spider's own check - IndeedCardsSpider's
    SIGNED_IN_COOKIES / OAUTH_SIGNED_IN_COOKIES. A script that declares
    success on cookies the spider does not accept produces a file that looks
    fine and crawls one page in fifteen.
'''
SITES = {
    "indeed": {
        "start_url": "https://tr.indeed.com/",
        "output": "indeed-storage-state.json",
        "env_var": "INDEED_STORAGE_STATE",
        "signed_in": (
            ("SOCK", "SHOE"),                       # native login
            ("__Secure-PassportAuthProxy-RefreshToken", "JSESSIONID"),  # Google
        ),
        "hint": "tr.indeed.com uzerinden NORMAL sekilde giris yap "
                "('Continue with Google' dahil), kendi hizinda.",
    },
    "linkedin": {
        # The login page directly rather than the feed: an anonymous visit to
        # linkedin.com/feed bounces through /authwall, which is one more
        # redirect between you and the form.
        "start_url": "https://www.linkedin.com/login",
        "output": "linkedin-storage-state.json",
        "env_var": "LINKEDIN_STORAGE_STATE",
        # li_at IS the LinkedIn session - one cookie, unlike Indeed's pair.
        # JSESSIONID is set for everyone, signed in or not, so it proves
        # nothing on its own and is deliberately not required here.
        "signed_in": (("li_at",),),
        "hint": "Burner hesapla giris yap. 2FA/dogrulama cikarsa pencerede "
                "tamamla - script bekliyor.",
    },
}


def _signed_in(cookies, groups):
    names = {c["name"] for c in cookies}
    return any(all(name in names for name in group) for group in groups)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SITES:
        print(f"kullanim: python -m tools.save_session <{'|'.join(SITES)}>")
        return 1

    site_key = sys.argv[1]
    site = SITES[site_key]
    output_path = os.path.join(REPO_ROOT, site["output"])

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
        page.goto(site["start_url"])

        print(
            f"Tarayici penceresi acildi ({site_key}). {site['hint']}\n"
            f"Giris otomatik algilanacak (en fazla {TIMEOUT_SECONDS}s bekleniyor)."
        )

        waited = 0
        while waited < TIMEOUT_SECONDS:
            if _signed_in(context.cookies(), site["signed_in"]):
                break
            time.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
        else:
            browser.close()
            print(
                f"{TIMEOUT_SECONDS}s icinde giris algilanamadi - pencere "
                f"kapatildi, hicbir sey kaydedilmedi. Tekrar calistir."
            )
            return 1

        context.storage_state(path=output_path)
        cookie_count = len(context.cookies())
        browser.close()

    print(f"Kaydedildi: {output_path} ({cookie_count} cookie dahil)")
    print(f"Simdi .env icine ekle: {site['env_var']}=" + output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
