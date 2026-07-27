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


#####################################################
# IT / SOFTWARE HINTS                               #
#####################################################
# Deliberately broad. This is not used to SELECT postings - it is used to
# protect them from being excluded, so a false positive here is harmless
# while a false negative throws away a real match.
IT_HINT_RE = re.compile(
    r"(yazılım|software|developer|geliştirici|geliştirme|bilgi işlem|bilişim|"
    r"\bit\b|\bict\b|bilgi teknoloji|information technolog|"
    r"data|veri (?:bilim|analiz|mühendis)|frontend|front.?end|backend|back.?end|"
    r"full.?stack|mobil|android|ios|web|devops|cloud|siber|cyber|security|"
    r"network|ağ |sistem|bilgisayar|computer|yapay zeka|machine learning|\bai\b|"
    r"\bllm\b|python|java|javascript|react|\.net|\bqa\b|test otomasyon|"
    r"database|veritabanı|sap|erp|teknoloji|technolog|mühendis|engineer)",
    re.IGNORECASE,
)

#####################################################
# FIELDS THAT ARE DEFINITELY NOT OURS               #
#####################################################
'''
    An EXCLUSION list, and the asymmetry is the whole point.

    A general "Stajyer" at UPS or "Intern" at pladis could be anything,
    including software - the employer simply has not said. Those must be kept:
    Turkish companies routinely advertise one internship and allocate people
    to departments afterwards.

    "Stajyer Diyetisyen" is not ambiguous. It says which field it is, and it
    is not this one. Dropping it loses nothing.

    So: throw away only what we KNOW is someone else's, never what we merely
    cannot identify. Measured against 120 real Istanbul internship postings,
    this removed 46 and kept all 57 ambiguous ones.

    Any IT hint cancels the exclusion, so "Cybersecurity Pre-Sales Stajyeri"
    survives despite "sales", and "Data Analyst Intern for License Compliance"
    survives despite "compliance".

    TUNE THIS AGAINST EACH SEARCH, NOT JUST ONE. The list was first calibrated
    on 120 internship postings and looked complete. The part-time search then
    turned out to have an entirely different composition: 32 of the first 164
    rows were childcare and domestic help - one agency, "enuygunbakıcı", was
    19% of the whole database on its own - and not one of them was caught.
    Different searches surface different neighbourhoods of the job market.
'''
OTHER_FIELD_RE = re.compile(
    # Care work and domestic help. NOT "evde" on its own - "evde çalışma"
    # means working from home, which is something we want.
    r"(bak[ıi]c[ıi]|dad[ıi]|au.?pair|ev yard[ıi]mc|"
    r"bebek|çocuk bak|çocuk oyun|evcil hayvan|hasta bak|ya[şs]l[ıi] bak|refakat|"
    r"temizlik|hijyen|ho[şs]geldin görevlis|kat görevlis|"
    # Unskilled / shift work
    r"kasiyer|komi|paketleme|depo eleman|servis görevlis|güvenlik görevlis|"
    r"avukat|hukuk|legal|"
    r"diyetisyen|psikolog|doktor|hemşire|paramedik|terapist|masaj|eczacı|"
    r"eczane|fizyoterap|"
    r"mimar|inşaat|"
    r"mutfak|aşçı|garson|barista|yiyecek|içecek|otelcilik|turizm|resepsiyon|"
    r"ön büro|housekeeping|"
    r"antrenör|fitness|spor salonu|"
    r"kuaför|güzellik|makyaj|tırnak|kirpik|estetik|"
    r"muhasebe|accounting|mali müşavir|\bymm\b|denetçi|"
    r"insan kaynak|human resource|\bhr\b|bordro|özlük|"
    r"grafik|graphic design|videograph|video editör|fotoğraf|"
    r"öğretmen|eğitmen|çocuk gelişimi|okul öncesi|"
    r"lojistik|depo|kurye|nakliye|gümrük|forwarding|warehouse|"
    r"sekreter|santral|çağrı merkezi|call center|resepsiyonist|"
    r"veri giriş|data entry|"
    r"tekstil|moda|konfeksiyon|"
    r"makine bakım|mekanik|kaynakçı|torna|"
    r"saha satış|mağaza|kasiyer|reyon)",
    re.IGNORECASE,
)


def looks_like_internship(*texts):
    """True when any of the given strings reads like an internship."""
    return bool(INTERNSHIP_TITLE_RE.search(" ".join(t or "" for t in texts)))


def has_it_hint(*texts):
    return bool(IT_HINT_RE.search(" ".join(t or "" for t in texts)))


def is_other_field(*texts):
    """
    True only when the text names a field that is definitely not software.
    Anything ambiguous returns False and is therefore kept.
    """
    joined = " ".join(t or "" for t in texts)
    if IT_HINT_RE.search(joined):
        return False
    return bool(OTHER_FIELD_RE.search(joined))


def looks_like_parttime(*texts):
    """True when any of the given strings reads like part-time work."""
    return bool(PARTTIME_TITLE_RE.search(" ".join(t or "" for t in texts)))


def is_wanted(*texts):
    """Either of the two - the set this bot collects."""
    return looks_like_internship(*texts) or looks_like_parttime(*texts)
