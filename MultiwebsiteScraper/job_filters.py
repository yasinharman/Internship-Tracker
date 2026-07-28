"""
SHARED VOCABULARY FOR SPOTTING INTERNSHIPS AND PART-TIME WORK
============================================================

Every job board so far has turned out to classify its own postings badly, so
the title has to be read as a second opinion. This module is the one place
that vocabulary lives - when a new phrasing is discovered on any site, it gets
added here and every spider benefits.

Evidence behind it, all from real postings:

    kariyer.net   22 of 26 internships were coded D (Dönemsel) or F
                  (Tam zamanlı) by the employer, never S (Staj). The site's
                  own working-type filter would have hidden 85% of them.

    techcareer    "Bilgisayar Mühendisliği Stajyeri" is absent from the
                  site's own typeOfWork=2,4 internship filter.

A WARNING ABOUT WHAT THIS CAN AND CANNOT DO
-------------------------------------------
Vocabulary can never be complete. "Career Experıence Drıve - IT
(Servıce&Operatıons)" is a real internship at Eczacıbaşı with neither "staj"
nor "intern" anywhere in its title, and no word list would ever have caught
it - the site's own internship search did.

That is the whole argument for the union pattern: a posting should be
reachable by at least two independent routes, so that one route's blind spot
is covered by the other's. Title matching is one route. The site's own
category or search page is the other. Neither is trusted alone.

WHAT THIS MODULE NO LONGER DOES
-------------------------------
It used to decide the FIELD as well - whether a posting was software work or
someone else's line of business - through a word list of excluded fields.
That list could not be finished. Turkish inflection defeats it: the list held
"temizlik", the posting said "Parttime Ofis Temizliği", and the possessive
suffix turns k into ğ so the match is lost. Widened twice by hand, it still
leaked 9 out of 9 on a real database ("Oyun Ablası", "Bulaşıkçısı", "Diş
Hekimi Asistanı"...).

The field decision now belongs to the LLM classifier (`classifier.py`), which
reads the posting rather than pattern-matching it. What stays here is the
cheap, certain part - is this an internship or part-time work - which is a
DISCOVERY question (whose detail page is worth fetching) and does not depend
on inflection, because "staj\\w*" and "part time" match their own suffixes.
"""

import re

#####################################################
# INTERNSHIP                                        #
#####################################################
# `staj\w*` covers staj, stajyer, stajyeri, stajyerlik, stajı.
# The word boundary around `intern` is what stops it firing on
# "International", which is common in job titles.
INTERNSHIP_TITLE_RE = re.compile(
    r"\b(staj\w*|intern(?:ship)?s?|trainee|co-?op)\b",
    re.IGNORECASE,
)

#####################################################
# PART-TIME                                         #
#####################################################
PARTTIME_TITLE_RE = re.compile(
    r"\b(part[\s\-_]?time|yarı[\s\-]?zamanlı|yari[\s\-]?zamanli|yarı[\s\-]?gün)\b",
    re.IGNORECASE,
)



def looks_like_internship(*texts):
    """True when any of the given strings reads like an internship."""
    return bool(INTERNSHIP_TITLE_RE.search(" ".join(t or "" for t in texts)))


def looks_like_parttime(*texts):
    """True when any of the given strings reads like part-time work."""
    return bool(PARTTIME_TITLE_RE.search(" ".join(t or "" for t in texts)))


def is_wanted(*texts):
    """Either of the two - the set this bot collects."""
    return looks_like_internship(*texts) or looks_like_parttime(*texts)
