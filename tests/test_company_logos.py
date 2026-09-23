"""
THE LOGO LAYER - pipeline/company_logos.py

Harman, 21.09.2026: "Logosu olmayan iş ilanları için yapay zeka internette
şirket ismini aratıp logoyu bulsun". The model names the company's site, this
code fetches it and reads the mark out of the page.

Nothing here reaches a model or the network: the model's answer and every
request are injected. The point of most of these is the guard - what happens
when the model names the WRONG site.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline import company_logos as logos
from scraper.models import Base, JobPost

APPLE = '''<html><head>
  <title>Arçelik - Ana Sayfa</title>
  <link rel="apple-touch-icon" sizes="180x180" href="/img/touch-180.png">
  <link rel="icon" sizes="32x32" href="/favicon-32.png">
  <meta property="og:image" content="https://arcelik.com.tr/social.jpg">
</head><body>Arçelik A.Ş.</body></html>'''


YES = lambda company, domain, page: True      # the model's second look, stubbed


def served(text, content_type="text/html"):
    return lambda url, want_image=False: logos.Fetched(
        url, 200, "" if want_image else text,
        "image/png" if want_image else content_type, 4096,
    )


####################################################
# WHAT THE MODEL SAYS, CLEANED UP                  #
####################################################
@pytest.mark.parametrize("raw, expected", [
    ("arcelik.com.tr", "arcelik.com.tr"),
    ("https://www.Arcelik.com.tr/kariyer", "arcelik.com.tr"),
    ("WWW.TCHIBO.COM.TR ", "tchibo.com.tr"),
    ("", None),
    ("bilmiyorum", None),
    ("Bu şirketi tanımıyorum.", None),
    # An intermediary is not the employer's site - and linkedin.com is where
    # a model reaches when it cannot place the company.
    ("linkedin.com", None),
    ("tr.linkedin.com", None),
    ("tr.indeed.com", None),
])
def test_clean_domain(raw, expected):
    assert logos.clean_domain(raw) == expected


####################################################
# THE GUARD AGAINST A HALLUCINATED SITE            #
####################################################
def test_the_domain_carrying_the_name_is_enough():
    assert logos.looks_like_the_company("<html>hoş geldiniz</html>",
                                        "arcelik.com.tr", "Arçelik A.Ş.")


def test_the_page_saying_the_name_is_enough():
    assert logos.looks_like_the_company(
        "<html><body>Estetik International Sağlık</body></html>",
        "esteticturkey.com", "Estetik International")


def test_a_page_that_never_says_the_company_is_refused():
    # The model named a real site that belongs to somebody else. The posting
    # keeps its initials rather than wearing another company's mark.
    assert not logos.looks_like_the_company(
        "<html><body>Bir başka şirketin sayfası</body></html>",
        "baskasirket.com", "Estetik International")


def test_turkish_letters_and_legal_forms_do_not_decide():
    assert logos.name_words("ARÇELİK A.Ş.") == ["arcelik"]
    assert logos.name_words("Şişecam Holding A.Ş.") == ["sisecam"]
    assert logos.looks_like_the_company("<p>ARCELIK</p>", "x.com", "Arçelik A.Ş.")


####################################################
# WHICH IMAGE ON THE PAGE                          #
####################################################
def test_the_apple_touch_icon_comes_first():
    assert logos.logo_candidates(APPLE, "https://arcelik.com.tr/")[0] == \
        "https://arcelik.com.tr/img/touch-180.png"


def test_the_largest_icon_before_the_smaller_one():
    page = ('<link rel="icon" sizes="16x16" href="/small.png">'
            '<link rel="shortcut icon" sizes="192x192" href="/big.png">')
    found = logos.logo_candidates(page, "https://x.com/")
    assert found[:2] == ["https://x.com/big.png", "https://x.com/small.png"]


def test_og_image_after_the_icons_and_favicon_last():
    page = ('<link rel="icon" href="/i.png">'
            '<meta property="og:image" content="/card.png">')
    assert logos.logo_candidates(page, "https://x.com/") == [
        "https://x.com/i.png", "https://x.com/card.png", "https://x.com/favicon.ico",
    ]


def test_a_page_with_nothing_still_offers_the_favicon():
    assert logos.logo_candidates("<html><body>hi</body></html>", "https://x.com/") == \
        ["https://x.com/favicon.ico"]


def test_an_empty_og_image_is_not_a_candidate():
    # Texas Instruments, 23.09.2026: content="" turned into the page's own
    # url, and an HTML document was offered as the company's logo.
    page = '<meta property="og:image" content="">'
    assert logos.logo_candidates(page, "https://www.ti.com/") == \
        ["https://www.ti.com/favicon.ico"]


####################################################
# THE WHOLE PATH FOR ONE COMPANY                   #
####################################################
def test_a_company_the_model_knows(caplog):
    url = logos.logo_for("Arçelik A.Ş.", ask=lambda c: "arcelik.com.tr",
                         fetcher=served(APPLE), confirm=YES)
    assert url == "https://arcelik.com.tr/img/touch-180.png"


def test_the_model_will_not_guess():
    # An empty answer is a good answer: the board keeps the initials.
    assert logos.logo_for("Bilinmeyen Ltd", ask=lambda c: None,
                          fetcher=served(APPLE), confirm=YES) is None


def test_a_site_that_is_down():
    down = lambda url, want_image=False: logos.Fetched(url, 0)
    assert logos.logo_for("Arçelik", ask=lambda c: "arcelik.com.tr",
                          fetcher=down, confirm=YES) is None


def test_a_wrong_site_writes_nothing():
    page = served("<html><body>Tamamen başka bir kurum</body></html>")
    assert logos.logo_for("Estetik International", ask=lambda c: "baskasirket.com",
                          fetcher=page, confirm=YES) is None


def test_every_candidate_being_html_writes_nothing():
    # A soft 404 on each: the icon paths answer 200 with an HTML error page.
    def fetcher(url, want_image=False):
        if want_image:
            return logos.Fetched(url, 200, "", "text/html", 512)
        return logos.Fetched(url, 200, APPLE, "text/html", 4096)

    assert logos.logo_for("Arçelik", ask=lambda c: "arcelik.com.tr",
                          fetcher=fetcher, confirm=YES) is None


def test_a_soft_404_on_the_first_candidate_falls_through_to_the_next():
    # FedEx and Estetik International, 23.09.2026: /favicon.ico answered with
    # HTML and the company lost its logo although the page offered another.
    def fetcher(url, want_image=False):
        if not want_image:
            return logos.Fetched(url, 200, APPLE, "text/html", 4096)
        if url.endswith("touch-180.png"):
            return logos.Fetched(url, 404, "", "text/html", 512)
        return logos.Fetched(url, 200, "", "image/png", 2048)

    assert logos.logo_for("Arçelik", ask=lambda c: "arcelik.com.tr",
                          fetcher=fetcher, confirm=YES) == "https://arcelik.com.tr/favicon-32.png"


def test_at_most_three_candidates_are_requested():
    asked = []

    def fetcher(url, want_image=False):
        if not want_image:
            return logos.Fetched(url, 200, APPLE, "text/html", 4096)
        asked.append(url)
        return logos.Fetched(url, 404, "", "text/html", 0)

    logos.logo_for("Arçelik", ask=lambda c: "arcelik.com.tr", fetcher=fetcher,
                   confirm=YES)
    assert len(asked) == logos.MAX_CANDIDATES


def test_a_domain_that_answers_nothing_is_retried_with_www():
    asked = []

    def fetcher(url, want_image=False):
        asked.append(url)
        if url == "https://www.arcelik.com.tr/":
            return logos.Fetched(url, 200, APPLE, "text/html", 4096)
        if want_image:
            return logos.Fetched(url, 200, "", "image/png", 2048)
        return logos.Fetched(url, 0)     # nothing answered on the bare name

    assert logos.logo_for("Arçelik", ask=lambda c: "arcelik.com.tr",
                          fetcher=fetcher, confirm=YES) is not None
    assert asked[:2] == ["https://arcelik.com.tr/", "https://www.arcelik.com.tr/"]


def test_a_placeholder_company_never_reaches_the_model(session):
    posting(session, company="N/A", n=1)
    posting(session, company="Arçelik", n=2)
    assert logos.companies_without_a_logo(session) == {"Arçelik": 1}


####################################################
# WHAT IS WRITTEN TO THE DATABASE                  #
####################################################
@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    made = sessionmaker(bind=engine)()
    yield made
    made.close()


def posting(session, **kwargs):
    row = JobPost(job_title="Stajyer", url=f"https://x/{kwargs.get('company')}"
                                            f"/{kwargs.pop('n', 1)}",
                  source_site="indeed.com",
                  is_active=kwargs.pop("is_active", True), **kwargs)
    session.add(row)
    session.commit()
    return row


def test_only_the_postings_without_one_are_counted(session):
    posting(session, company="Arçelik", n=1)
    posting(session, company="Arçelik", n=2)
    posting(session, company="Tchibo", n=3, company_logo_url="https://t/logo.png")
    posting(session, company="Kapalı", n=4, is_active=False)

    waiting = logos.companies_without_a_logo(session)
    assert waiting == {"Arçelik": 2}


def test_the_write_never_overwrites_a_crawled_logo(session):
    posting(session, company="Arçelik", n=1)
    posting(session, company="Arçelik", n=2, company_logo_url="https://own/x.png")

    assert logos.write_logo(session, "Arçelik", "https://found/logo.png") == 1
    stored = {row.company_logo_url for row in session.query(JobPost).all()}
    assert stored == {"https://own/x.png", "https://found/logo.png"}


####################################################
# THE BRAND IS THE FIRST WORD - measured 23.09.2026 #
####################################################
# The first dry run skipped "ABB Elektrik Sanayi A.S." although the model had
# named abb.com correctly: the guard was matching on the longest word,
# "elektrik", which ABB's global page never says.

def test_abb_is_not_skipped_for_not_saying_elektrik():
    assert logos.looks_like_the_company(
        "<html><body>ABB is a technology leader</body></html>",
        "abb.com", "ABB Elektrik Sanayi A.S.")


def test_a_longer_registration_of_the_same_brand():
    assert logos.looks_like_the_company("<html>x</html>", "baykartech.com", "Baykar")


def test_a_three_letter_brand_needs_the_whole_label():
    # "abb" inside another word is a coincidence, not a company.
    assert not logos.looks_like_the_company(
        "<html><body>message broker</body></html>", "rabbitmq.com",
        "ABB Elektrik Sanayi A.S.")


####################################################
# THE SAME NAME, A DIFFERENT COMPANY - 23.09.2026  #
####################################################
# pladis, the snacking company whose posting we hold, passed the string guard
# on pladis.com: the domain IS the brand. That site is "Diseño y Construcción
# | Pladis", a Spanish construction firm. No string comparison can see it, so
# the model gets a second look at what the page says about itself.

def test_the_model_can_veto_a_same_name_site():
    said_no = lambda company, domain, page: False
    assert logos.logo_for("pladis", ask=lambda c: "pladis.com",
                          fetcher=served(APPLE), confirm=said_no) is None


def test_the_page_summary_is_what_the_site_says_about_itself():
    page = ('<html><head><title>Diseño y Construcción | Pladis</title>'
            '<meta name="description" content="Estudio de arquitectura">'
            '<meta property="og:site_name" content="Pladis Arquitectos">'
            '</head></html>')
    summary = logos.page_summary(page)
    assert "Diseño y Construcción | Pladis" in summary
    assert "Pladis Arquitectos" in summary
    assert "Estudio de arquitectura" in summary


def test_a_page_with_nothing_to_say_is_not_sent_to_the_model():
    # No title, no description: the string guard's verdict stands rather than
    # asking the model about an empty page.
    calls = []
    assert logos.confirms_the_company(
        "Arçelik", "arcelik.com.tr", "<html><body>x</body></html>",
        client=calls.append) is True
    assert calls == []
