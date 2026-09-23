"""
THE FIELDS A POSTING BELONGS TO
===============================

The board stopped being a software board on 21.09.2026. Harman, 23.09.2026:
"kapsamlı bir sınıflandırma şeması yapıp bütün staj ilanlarını görünür
yapmamız gerekiyor. Öğrenciler kendileri görmek istediği ilan türlerine göre
filtreleme yapacak".

So this replaces `it / general_program / other`, where `other` did not mean a
field at all - it meant "hidden". A cleaner's posting and a lawyer's posting
were the same category, and the same category meant gone. Here every posting
gets the field or fields a student would look under, nothing is hidden for
being in a field, and the student picks.

MORE THAN ONE FIELD, ON PURPOSE
-------------------------------
"Yazılım ve Veri Stajyeri" is both, "Elektrik-Elektronik / Otomasyon" is one
field written as two, and a bank's "Finans Teknolojileri Stajyeri" is finance
and software at once. Forcing one label means choosing which half of those
postings to lose. A posting carries between one and MAX_FIELDS, the first
being the one it is mostly about - that one is stored on the posting itself
(JobPost.job_category), and all of them in job_post_fields, which is what the
dashboard filters on.

GENEL_PROGRAM IS NOT A FIELD EITHER, and it is kept for the reason it was
invented: a company-wide internship that never names a department could turn
out to be any of these, and a student filtering for their own field should
still see it. It never travels with another label - a posting either names
what it wants or it does not.

CHANGING THE LIST is a two-line edit here, but it is not free: the model was
measured on this exact vocabulary, every stored posting was sorted with it,
and both have to be redone. docs/pipeline.md keeps the measurements.
"""

# slug -> what the dashboard shows. The slug is what the database and the URL
# carry, so it stays ASCII: a filter that reads ?categories=yazilim survives
# copy-paste, a mail client and a terminal, which ?categories=yazılım does not.
FIELDS = {
    # Bilişim
    "yazilim": "Yazılım",
    "veri_yapay_zeka": "Veri ve yapay zekâ",
    "siber_guvenlik_sistem": "Siber güvenlik, sistem ve ağ",
    # Mühendislik
    "elektrik_elektronik": "Elektrik-elektronik ve otomasyon",
    "makine_mekatronik": "Makine, mekatronik ve otomotiv",
    "insaat_mimarlik": "İnşaat, mimarlık ve harita",
    "endustri_uretim": "Endüstri, üretim ve kalite",
    "kimya_biyoloji_gida": "Kimya, biyoloji, gıda ve çevre",
    # İşletme
    "finans_muhasebe": "Finans, muhasebe ve denetim",
    "isletme_yonetim": "İşletme, yönetim ve proje",
    "insan_kaynaklari": "İnsan kaynakları",
    "lojistik_tedarik": "Lojistik, tedarik ve dış ticaret",
    # Ticaret ve iletişim
    "pazarlama_reklam": "Pazarlama ve reklam",
    "satis_musteri": "Satış ve müşteri ilişkileri",
    "medya_iletisim": "Medya, iletişim ve gazetecilik",
    "tasarim": "Tasarım",
    # Diğer alanlar
    "hukuk": "Hukuk",
    "egitim": "Eğitim",
    "saglik": "Sağlık",
    "turizm_otelcilik": "Turizm, otelcilik ve yiyecek-içecek",
    "ofis_idari": "Ofis ve idari işler",
    "hizmet_perakende": "Hizmet, perakende ve operasyon",
    "tarim_veterinerlik": "Tarım, ziraat ve veterinerlik",
    # Ne alan söyleyen ne de başka bir yere sığan
    "genel_program": "Bütün bölümlere açık program",
    "diger": "Diğer",
}

# What the dashboard groups them under. Only an ordering and a heading - the
# database never stores a group, so regrouping costs nothing.
GROUPS = {
    "Bilişim": ["yazilim", "veri_yapay_zeka", "siber_guvenlik_sistem"],
    "Mühendislik": ["elektrik_elektronik", "makine_mekatronik", "insaat_mimarlik",
                    "endustri_uretim", "kimya_biyoloji_gida"],
    "İşletme": ["finans_muhasebe", "isletme_yonetim", "insan_kaynaklari",
                "lojistik_tedarik"],
    "Ticaret ve iletişim": ["pazarlama_reklam", "satis_musteri", "medya_iletisim",
                            "tasarim"],
    "Diğer alanlar": ["hukuk", "egitim", "saglik", "turizm_otelcilik",
                      "ofis_idari", "hizmet_perakende", "tarim_veterinerlik"],
    "Belirtilmemiş": ["genel_program", "diger"],
}

# A posting that is about three things is a posting that is about nothing in
# particular; past three the labels stop meaning "look here" and start meaning
# "this could be anything", which genel_program already says.
MAX_FIELDS = 3

# The two that never share a posting with a real field, for the reason in the
# docstring: they are statements about the ABSENCE of one.
ALONE = {"genel_program", "diger"}

ORDER = [slug for slugs in GROUPS.values() for slug in slugs]


def label(slug):
    return FIELDS.get(slug, slug)


def group_of(slug):
    for name, slugs in GROUPS.items():
        if slug in slugs:
            return name
    return "Belirtilmemiş"


def clean(slugs):
    """
    What is actually stored, out of what the model answered.

    Unknown slugs are dropped rather than stored: the model is asked for
    these and only these, and a spelling it invented would become a filter
    option nobody can choose from the dashboard.
    """
    seen, kept = set(), []
    for slug in slugs or []:
        slug = (slug or "").strip().lower()
        if slug in FIELDS and slug not in seen:
            seen.add(slug)
            kept.append(slug)

    # A real field wins over "could be anything": a model that answers
    # ["yazilim", "genel_program"] has named a department, so the posting
    # belongs under yazilim and nowhere near the catch-all.
    named = [slug for slug in kept if slug not in ALONE]
    if named:
        kept = named
    elif kept:
        kept = kept[:1]

    return kept[:MAX_FIELDS] or ["diger"]
