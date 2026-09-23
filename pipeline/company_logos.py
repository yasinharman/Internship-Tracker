"""
A LOGO FOR THE POSTINGS THAT ARRIVED WITHOUT ONE
================================================

    python -m pipeline.company_logos                  fill them in
    python -m pipeline.company_logos --dry-run        say what it would do
    python -m pipeline.company_logos --limit 5        the first five companies

Every board but one hands the crawl a logo with the card. Indeed does not:
on 23.09.2026 all 104 of its active postings had `company_logo_url` NULL,
against 0 of kariyer.net's 24, LinkedIn's 70 and Youthall's 13. The dashboard
falls back to the company's initials, which is honest but plain.

Harman asked for this layer on 21.09.2026: "Logosu olmayan iş ilanları için
yapay zeka internette şirket ismini aratıp logoyu bulsun". It is the last
thing on the list, on purpose - nothing else waits on it.

WHAT "SEARCHES THE WEB" MEANS HERE
----------------------------------
The model is gemma4:12b behind Ollama, on this machine. It cannot fetch
anything: Ollama answers from what the model knows and makes no requests of
its own. So the two halves are split -

    the model   names the company's official website from its name
    this code   fetches that site and reads the logo out of its HTML

which is also what makes a wrong answer cheap to catch. A model that invents
a domain is caught by `looks_like_the_company`: the page has to say the
company's name somewhere, or nothing is written and the board keeps its
initials. A missing logo is a plain board. A WRONG logo is another company's
mark on someone's job posting.

NO JOB BOARD IS TOUCHED. The only requests are to the company's own site, one
or two per company, and to nothing else. Companies, not postings: 104 Indeed
postings on 23.09 came from 33 companies.

WHAT IS STORED: a url on the company's own server, hotlinked, the same shape
the crawl stores for the other boards (scraper/models.py, "THE EMPLOYER'S
MARK"). Nothing is downloaded and nothing is copied into this repo.
"""

import argparse
import logging
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from dotenv import load_dotenv
from lxml import html as lxml_html
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from scraper.models import JobPost, db_connect

# Same as every other step in pipeline/: run with -m from the repository root,
# so .env is here.
load_dotenv()

logger = logging.getLogger("company_logos")

# The same model the classifier uses, and the same request: one local server,
# one measured configuration (scraper/classifier.py, "ONE LOCAL MODEL").
from scraper.classifier import DEFAULT_MODEL, LOCAL_BASE_URL, LOCAL_REQUEST

# A company's own site, asked for politely and one at a time. These are not
# job boards and none of them has refused us, but the pacing is the same
# habit: nothing here is urgent enough to arrive in a burst.
PAUSE_BETWEEN_COMPANIES_S = float(os.getenv("LOGO_PAUSE_S", "2"))
FETCH_TIMEOUT_S = float(os.getenv("LOGO_FETCH_TIMEOUT", "15"))

# A browser's own header set, not because anything has challenged us - no
# company site has - but because a bare python-requests User-Agent is the one
# thing a WAF reads as automation before it has read anything else.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like "
        "Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


#####################################################
# WHAT THE MODEL IS ASKED, AND WHAT COMES BACK      #
#####################################################
class CompanySite(BaseModel):
    domain: str          # "arcelik.com.tr", or "" when the model does not know
    reason: str          # one sentence, Turkish - printed, not stored


# Deliberately narrow. The model is not asked for a logo url: it has no way to
# know one and would produce a plausible path that 404s, or worse, one that
# resolves to something else. It is asked for the one fact a language model
# genuinely carries about a company - where it lives on the web - and the
# fetching is left to code that can check.
SYSTEM_PROMPT = """\
Sana bir şirket adı verilecek. Bu şirketin RESMİ web sitesinin alan adını \
söyle.

Kurallar:
- Sadece alan adını yaz: "arcelik.com.tr" gibi. Başına https:// veya www. \
  ekleme, sonuna yol ekleme.
- Türkiye'de faaliyet gösteren bir şirketse yerel alan adını tercih et \
  (".com.tr" gibi), yoksa küresel adresini yaz.
- Şirketi tanımıyorsan ya da emin değilsen `domain` alanını BOŞ BIRAK. \
  Uydurma. Yanlış alan adı, ilanın üzerinde başka bir şirketin logosunun \
  görünmesi demektir.
- LinkedIn, Kariyer.net, Indeed, Facebook gibi ARACI siteleri verme; \
  şirketin kendi sitesini ver.
- `reason` alanına tek bir Türkçe cümle yaz.\
"""


def ask_for_the_site(company, model=None, client=None):
    """The model's answer for one company name. None when it will not say."""
    from openai import OpenAI

    model = model or os.getenv("LOGO_MODEL") or os.getenv("CLASSIFIER_MODEL") or DEFAULT_MODEL
    client = client or OpenAI(
        base_url=os.getenv("CLASSIFIER_URL") or LOCAL_BASE_URL,
        api_key="local",
    )

    parse = getattr(client.chat.completions, "parse", None)
    if parse is None:
        parse = client.beta.chat.completions.parse

    completion = parse(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Şirket: {company}"},
        ],
        response_format=CompanySite,
        **LOCAL_REQUEST,
    )
    answer = completion.choices[0].message.parsed
    domain = clean_domain(answer.domain if answer else "")
    if domain:
        logger.info("%s -> %s (%s)", company, domain, answer.reason)
    else:
        logger.info("%s -> the model would not name a site (%s)", company,
                    answer.reason if answer else "no answer")
    return domain


# Intermediaries. A model that cannot place a company reaches for the site it
# saw the company ON, which is exactly where the posting came from and carries
# that board's logo, not the employer's.
NOT_A_COMPANY_SITE = {
    "linkedin.com", "indeed.com", "tr.indeed.com", "kariyer.net",
    "techcareer.net", "youthall.com", "glassdoor.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "wikipedia.org", "google.com",
    "secretcv.com", "eleman.net", "yenibiris.com",
}


def clean_domain(raw):
    """
    "https://www.Arçelik.com.tr/kariyer" -> "arcelik.com.tr". None if unusable.

    The model is told to answer with a bare domain and mostly does; this is
    for the times it does not, which is cheaper to absorb than to re-prompt.
    """
    text = (raw or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/")[0].split("?")[0].strip().strip(".")
    if text.startswith("www."):
        text = text[4:]
    # A domain, not a sentence: letters, digits, dashes and dots, with a tld.
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", text):
        return None
    if any(text == bad or text.endswith("." + bad) for bad in NOT_A_COMPANY_SITE):
        return None
    return text


#####################################################
# IS THIS REALLY THAT COMPANY'S PAGE?               #
#####################################################
# Legal forms and the noise around them. "Arçelik A.Ş." and "ARÇELİK" are the
# same employer; the suffix is never the distinguishing part of a name.
LEGAL_FORMS = {
    "a.ş.", "a.ş", "aş", "as", "ltd", "ltd.", "şti", "şti.", "sti", "sti.",
    "inc", "inc.", "llc", "gmbh", "bv", "b.v.", "nv", "plc", "co", "co.",
    "corp", "corp.", "holding", "group", "grubu", "company", "sanayi",
    "ticaret", "san", "tic", "ve", "and", "the",
}

TURKISH_FOLD = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")


def normalise(text):
    """Lowercase, Turkish letters folded, punctuation gone."""
    folded = (text or "").translate(TURKISH_FOLD).lower()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def name_words(company):
    """The words of a company name that actually identify it."""
    return [
        word for word in normalise(company).split()
        if len(word) >= 3 and word not in {normalise(f) for f in LEGAL_FORMS}
    ]


def the_brand(company):
    """
    The word that identifies the employer - the first real word of the name.

    MEASURED 23.09.2026, and it is why this is not "the longest word": the
    first dry run skipped "ABB Elektrik Sanayi A.S." although the model had
    named abb.com, its real site. The guard was matching on the longest word,
    "elektrik", which the global page never says. The brand is at the front
    of a Turkish company name and the rest describes the trade.
    """
    words = name_words(company)
    return words[0] if words else None


def looks_like_the_company(page_text, domain, company):
    """
    Does this page belong to the company the posting named?

    The guard against a hallucinated domain, and the reason this layer is
    safe to run unattended. Three ways to pass, cheapest first:

      - a label of the domain IS the brand ("abb.com" for ABB);
      - a label STARTS with it, for the longer names companies register
        ("baykartech.com" for Baykar) - four letters and up, or "abb" would
        pass on "rabbitmq.com";
      - the page says the brand, or the name's longest word, in its text.

    A company whose site says none of these keeps its initials on the board.
    That is the trade this is written around: a missing logo is plain, a
    wrong logo is a lie about whose posting it is.
    """
    words = name_words(company)
    brand = the_brand(company)
    if not brand:
        return False

    labels = normalise(domain).split()
    for label in labels:
        if label == brand:
            return True
        if len(brand) >= 4 and brand in label:
            return True

    haystack = f" {normalise(page_text)} "
    longest = max(words, key=len)
    return f" {brand} " in haystack or f" {longest} " in haystack


#####################################################
# AND IS IT THE SAME COMPANY? - the model's second look
#####################################################
class SameCompany(BaseModel):
    same: bool
    reason: str          # one sentence, Turkish - logged, not stored


CONFIRM_PROMPT = """\
Sana bir iş ilanındaki ŞİRKET ADI ve bir web sitesinin başlığı, açıklaması \
ve alan adı verilecek. Bu sitenin O ŞİRKETE ait olup olmadığına karar ver.

- Aynı ada sahip BAŞKA bir şirketin sitesi olabilir. Sektör, ülke ve dil \
  uyuşmuyorsa `same` alanını false yap.
- Şirketin ülkeye özel sitesi (".com.tr" gibi) ya da küresel sitesi olması \
  sorun değil, ikisi de aynı şirkettir.
- Emin değilsen false de. Yanlış site, ilanın üzerinde başka bir şirketin \
  logosunun görünmesi demektir.
- `reason` alanına tek bir Türkçe cümle yaz.\
"""


def page_summary(page_html):
    """Title, description and og:site_name - what a page says about itself."""
    try:
        tree = lxml_html.fromstring(page_html)
    except Exception:
        return ""
    title = (tree.xpath("//title/text()") or [""])[0].strip()
    description = (tree.xpath('//meta[@name="description"]/@content') or [""])[0].strip()
    site_name = (tree.xpath('//meta[@property="og:site_name"]/@content') or [""])[0].strip()
    parts = [f"Başlık: {title}"]
    if site_name:
        parts.append(f"Site adı: {site_name}")
    if description:
        parts.append(f"Açıklama: {description[:300]}")
    return "\n".join(parts)


def confirms_the_company(company, domain, page_html, client=None, model=None):
    """
    The model's second look, and the answer to the case the cheap guard
    cannot see.

    MEASURED 23.09.2026. pladis - the snacking company whose posting we hold -
    passed `looks_like_the_company` on pladis.com, because the domain IS the
    brand. pladis.com is "Diseño y Construcción | Pladis", a Spanish design
    and construction firm with the same name. The name matching is exactly
    right and the company is exactly wrong, and no string comparison can tell
    the two apart. This asks the model, which costs no request.
    """
    from openai import OpenAI

    summary = page_summary(page_html)
    if not summary.replace("Başlık:", "").strip():
        # A page with no title, description or site name says nothing to ask
        # about. The string guard has already passed; leave it at that.
        return True

    model = model or os.getenv("LOGO_MODEL") or os.getenv("CLASSIFIER_MODEL") or DEFAULT_MODEL
    client = client or OpenAI(
        base_url=os.getenv("CLASSIFIER_URL") or LOCAL_BASE_URL,
        api_key="local",
    )
    parse = getattr(client.chat.completions, "parse", None)
    if parse is None:
        parse = client.beta.chat.completions.parse

    completion = parse(
        model=model,
        messages=[
            {"role": "system", "content": CONFIRM_PROMPT},
            {"role": "user",
             "content": f"İlandaki şirket: {company}\nAlan adı: {domain}\n{summary}"},
        ],
        response_format=SameCompany,
        **LOCAL_REQUEST,
    )
    answer = completion.choices[0].message.parsed
    if answer is None:
        return True
    if not answer.same:
        logger.info("%s: %s is somebody else - %s", company, domain, answer.reason)
    return bool(answer.same)


#####################################################
# THE LOGO IN THE PAGE                              #
#####################################################
def _icon_size(link):
    """The bigger number in sizes="180x180". 0 when it says nothing."""
    sizes = (link.get("sizes") or "").lower().strip()
    numbers = [int(n) for n in re.findall(r"\d+", sizes)]
    return max(numbers) if numbers else 0


def logo_candidates(page_html, page_url):
    """
    Every mark this page offers, best first, as absolute urls.

    A LIST, not one url - measured 23.09.2026. The first run picked one
    candidate and gave up when it was not an image, which lost FedEx and
    Estetik International to a soft 404 on /favicon.ico. The next candidate
    down would have served.

    The order, and why:
      1. apple-touch-icon - a square, transparent-background logo meant to sit
         on a home screen. That is exactly the shape the dashboard's avatar
         wants, and it is the one icon a site publishes at a usable size.
      2. <link rel="icon"> with the largest sizes= - same idea, smaller.
      3. og:image - a SOCIAL CARD, usually a wide banner with text. Below the
         icons because it fills the avatar with a slogan more often than a
         mark.
      4. /favicon.ico - not in the HTML at all, but the path every browser
         tries. 16x16 is poor, and it is still better than initials.
    """
    try:
        tree = lxml_html.fromstring(page_html)
    except Exception:
        return []

    def lowered(attribute):
        return (f'translate(@{attribute}, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", '
                f'"abcdefghijklmnopqrstuvwxyz")')

    found = []
    apple = tree.xpath(f'//link[contains({lowered("rel")}, "apple-touch-icon")][@href]')
    found += [link.get("href") for link in sorted(apple, key=_icon_size, reverse=True)]

    icons = [link for link in tree.xpath(f'//link[contains({lowered("rel")}, "icon")][@href]')
             if "apple" not in (link.get("rel") or "").lower()]
    found += [link.get("href") for link in sorted(icons, key=_icon_size, reverse=True)]

    found += [meta.get("content") for meta in
              tree.xpath('//meta[@property="og:image" or @name="og:image"][@content]')]

    # An empty href or content is not a candidate. Texas Instruments ships
    # <meta property="og:image" content="">, and urljoin turned that into the
    # page's own url - an HTML document offered as a logo.
    urls = [urljoin(page_url, value.strip()) for value in found if (value or "").strip()]
    urls.append(urljoin(page_url, "/favicon.ico"))

    seen, ordered = set(), []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


#####################################################
# FETCHING                                          #
#####################################################
class Fetched:
    """What one request came back with. Kept tiny so tests can build one."""

    def __init__(self, url, status, text="", content_type="", length=0):
        self.url = url
        self.status = status
        self.text = text
        self.content_type = content_type
        self.length = length


def fetch(url, want_image=False):
    """One request. Never raises - a company site being down is not an error."""
    try:
        reply = requests.get(
            url, headers=BROWSER_HEADERS, timeout=FETCH_TIMEOUT_S,
            allow_redirects=True, stream=want_image,
        )
    except requests.RequestException as error:
        logger.info("%s: %s", url, type(error).__name__)
        return Fetched(url, 0)

    content_type = (reply.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if want_image:
        # The bytes are not wanted, only the verdict: is there an image here?
        length = int(reply.headers.get("Content-Length") or 0)
        reply.close()
        return Fetched(reply.url, reply.status_code, "", content_type, length)
    return Fetched(reply.url, reply.status_code, reply.text, content_type,
                   len(reply.content))


# How many of a page's candidates are worth a request. Three covers
# apple-touch-icon, the biggest <link rel=icon> and /favicon.ico; past that a
# page is not telling us where its mark is.
MAX_CANDIDATES = 3


def logo_for(company, ask=None, fetcher=None, confirm=confirms_the_company):
    """
    One company -> one logo url, or None with the reason logged.

    `ask`, `fetcher` and `confirm` are injected so the tests can run the whole
    path without a model or a network.
    """
    ask = ask or ask_for_the_site
    fetcher = fetcher or fetch

    domain = ask(company)
    if not domain:
        return None

    page = fetcher(f"https://{domain}/")
    if page.status == 0 and not domain.startswith("www."):
        # Nothing answered at all - no DNS, or the connection was refused.
        # Some hosts only serve the www name. One retry, measured worth it on
        # 23.09.2026 when six domains came back with nothing.
        page = fetcher(f"https://www.{domain}/")
    if page.status != 200 or not page.text:
        logger.info("%s: %s answered %s", company, domain, page.status or "nothing")
        return None

    if not looks_like_the_company(page.text, domain, company):
        logger.info("%s: %s does not say the company's name - skipped",
                    company, domain)
        return None

    if confirm and not confirm(company, domain, page.text):
        return None

    candidates = logo_candidates(page.text, page.url)[:MAX_CANDIDATES]
    for candidate in candidates:
        image = fetcher(candidate, want_image=True)
        if image.status == 200 and image.content_type.startswith("image/"):
            logger.info("%s: %s", company, candidate)
            return candidate
        logger.debug("%s: %s is not an image (%s %s)", company, candidate,
                     image.status, image.content_type or "no type")

    logger.info("%s: none of %s candidate(s) on %s was an image",
                company, len(candidates), domain)
    return None


#####################################################
# THE RUN                                           #
#####################################################
def companies_without_a_logo(session):
    """
    Company -> how many of its active postings are missing a logo.

    Grouped by company because the mark belongs to the employer, not to the
    posting: 104 Indeed postings on 23.09.2026 were 33 companies, so this is
    33 model calls and at most 66 requests instead of 208.
    """
    rows = (
        session.query(JobPost.company)
        .filter(JobPost.company_logo_url.is_(None))
        .filter(JobPost.is_active.is_(True))
        .filter(JobPost.duplicate_of.is_(None))
        .filter(JobPost.company.isnot(None))
        .all()
    )
    counted = {}
    for (company,) in rows:
        name = (company or "").strip()
        if name and not is_a_placeholder(name):
            counted[name] = counted.get(name, 0) + 1
    return counted


# What a spider writes when a card carried no company name (the crawl's
# DEFAULT_VALUE). Asking a model for "N/A"'s website wastes a call and invites
# it to invent one.
PLACEHOLDERS = {"n/a", "na", "-", "bilinmiyor", "unknown", "belirtilmemiş"}


def is_a_placeholder(company):
    return normalise(company).replace(" ", "") in {
        normalise(name).replace(" ", "") for name in PLACEHOLDERS
    }


def write_logo(session, company, url):
    """Only onto the rows that have none - never over a logo the crawl found."""
    updated = (
        session.query(JobPost)
        .filter(JobPost.company == company)
        .filter(JobPost.company_logo_url.is_(None))
        .update({JobPost.company_logo_url: url}, synchronize_session=False)
    )
    session.commit()
    return updated


def run(limit=None, dry_run=False):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    engine = db_connect()
    session = sessionmaker(bind=engine)()
    try:
        waiting = companies_without_a_logo(session)
        names = sorted(waiting, key=lambda name: -waiting[name])
        if limit:
            names = names[:limit]
        print(f"{len(waiting)} company/companies without a logo, "
              f"{sum(waiting.values())} posting(s). Working on {len(names)}.",
              flush=True)

        found = rows_written = 0
        for index, company in enumerate(names, start=1):
            if index > 1:
                time.sleep(PAUSE_BETWEEN_COMPANIES_S)
            try:
                url = logo_for(company)
            except Exception as error:
                # One company's site is not worth the run. A model that is
                # down, though, fails the same way for every company, and the
                # log says which it was.
                logger.warning("%s: %s", company, error)
                continue
            if not url:
                continue
            found += 1
            if dry_run:
                print(f"  (dry run) {company}: {url}", flush=True)
                continue
            rows_written += write_logo(session, company, url)

        print(f"{found} logo(s) found for {len(names)} company/companies, "
              f"{rows_written} posting(s) updated"
              f"{' (DRY RUN - nothing written)' if dry_run else ''}.", flush=True)
        return 0
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Find the logos, write nothing.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Work on this many companies, busiest first.")
    args = parser.parse_args()
    sys.exit(run(limit=args.limit, dry_run=args.dry_run))
