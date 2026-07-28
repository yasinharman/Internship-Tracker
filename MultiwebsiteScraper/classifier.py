"""
LLM FIELD CLASSIFICATION
========================

Decides, for one posting, whether it belongs to a software person:

    it                a software / IT role
    general_program   a company-wide internship with no department named yet
    other             someone else's line of work

Why an LLM and not a word list: Turkish inflection. The old list held
"temizlik", the posting said "Parttime Ofis Temizliği", and the possessive
suffix turns k into ğ - so the match is lost. Widened by hand twice, it still
leaked 9 out of 9 on a real database. See job_filters for the full argument.

WHY `general_program` EXISTS
----------------------------
"Intern" at UPS could be anything, including software - the employer has not
said which department yet, and Turkish companies routinely advertise one
internship for the whole company and allocate people afterwards. Throwing that
away loses real matches, so it gets its own category and stays visible. Only
postings that NAME a different field are dropped.

TWO PROVIDERS, ONE PROMPT
-------------------------
The schema, the prompt, and the parsing are shared; only the API call differs
(~40 lines each). That seam exists because the provider is chosen by
measurement - classify_jobs.py --compare runs the same postings through
several models and prints only the disagreements. It is not an abstraction
kept "in case we switch" later.

    LLM_PROVIDER       openai | anthropic
    CLASSIFIER_MODEL   e.g. gpt-5.4-nano, claude-haiku-4-5
"""

import logging
import os

from pydantic import BaseModel
from typing import Literal

logger = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "openai": "gpt-5.4-nano",
    "anthropic": "claude-haiku-4-5",
}

# How much of the description is worth sending. The title decides most cases;
# the description is there to break ties ("Stajyer" at a software house). Full
# descriptions run to several thousand characters of boilerplate about company
# culture, which costs tokens and adds nothing.
DESCRIPTION_CHARS = 1500


#####################################################
# WHAT COMES BACK                                   #
#####################################################
class JobCategory(BaseModel):
    category: Literal["it", "general_program", "other"]
    reason: str          # one sentence, Turkish - shown in the dashboard


#####################################################
# THE PROMPT                                        #
#####################################################
# Examples are real rows from our own database, including the ones the regex
# missed. Kept stable so it can be cached by both providers.
SYSTEM_PROMPT = """\
Sen bir iş ilanı sınıflandırıcısısın. Sana bir staj veya part-time ilanı \
verilecek; bunun bir YAZILIM/BİLİŞİM öğrencisine uygun olup olmadığına karar \
vereceksin.

Üç kategori var:

1. "it" — ilan açıkça yazılım, bilişim, veri, siber güvenlik, test/QA, DevOps, \
   sistem/ağ, yapay zeka veya bilgisayar mühendisliği alanında.
   Örnekler: "Software Engineering Intern (GE)", "Bilgisayar Mühendisliği \
   Stajyeri", "Part Time Working Student (DevOps Engineer)", "Cybersecurity \
   Pre-Sales Stajyeri"

2. "general_program" — şirket geneline açık bir staj/yetenek programı; ilan \
   hangi departmanda çalışılacağını SÖYLEMİYOR. Departman sonradan belli \
   oluyor, dolayısıyla yazılım da çıkabilir.
   Örnekler: "Intern (UPS)", "Stajyer", "Yaz Stajı Programı", "Kariyer Test \
   Sürüşü"

3. "other" — ilan BAŞKA bir alanı açıkça adlandırıyor.
   Örnekler: "Avcılar Yarı Zamanlı Oyun Ablası Aranıyor", "Karakazan \
   Bulaşıkçısı - Part Time", "Parttime Ofis Temizliği", "Part Time Diş Hekimi \
   Asistanı", "Gıda Mühendisi (Freelance)", "Sales Intern", "İnsan Kaynakları \
   Stajyeri"

EN ÖNEMLİ KURAL: "it" ile "general_program" arasında kararsız kalırsan \
"general_program" seç. Bilinmeyeni atmıyoruz — yanlış eleme, gerçek bir \
fırsatı kaybettirir; fazladan gösterilen bir ilan ise sadece bir satır gürültü.

Alan adı geçmiyorsa "other" DEME. "other" yalnızca ilan başka bir mesleği \
açıkça söylediğinde kullanılır.

`reason` alanına kararının gerekçesini TEK bir Türkçe cümleyle yaz; ilandaki \
hangi ifadeye dayandığını belirt.\
"""


def build_user_text(posting):
    """
    posting: any object with job_title / company / location / job_description.
    Works with both a JobPost row and a plain dict-like stand-in.
    """
    def field(name):
        if isinstance(posting, dict):
            return posting.get(name) or ""
        return getattr(posting, name, None) or ""

    description = field("job_description")[:DESCRIPTION_CHARS]

    return (
        f"Başlık: {field('job_title')}\n"
        f"Şirket: {field('company')}\n"
        f"Konum: {field('location')}\n"
        f"Açıklama: {description}"
    )


#####################################################
# OPENAI                                            #
#####################################################
def _classify_openai(user_text, model):
    from openai import OpenAI

    client = OpenAI()

    # The SDK moved this off the `beta` namespace; both spellings are still in
    # the wild, so take whichever this installation has.
    parse = getattr(client.chat.completions, "parse", None)
    if parse is None:
        parse = client.beta.chat.completions.parse

    completion = parse(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        response_format=JobCategory,
    )
    return completion.choices[0].message.parsed


#####################################################
# ANTHROPIC                                         #
#####################################################
def _classify_anthropic(user_text, model):
    import anthropic

    client = anthropic.Anthropic()

    response = client.messages.parse(
        model=model,
        max_tokens=512,
        # The cache_control marker is free to leave in: below the model's
        # minimum cacheable prefix it simply does nothing, and if the prompt
        # grows past it later this starts paying off without a code change.
        # Verify with response.usage.cache_read_input_tokens.
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_text}],
        output_format=JobCategory,
    )
    return response.parsed_output


#####################################################
# ONE POSTING -> ONE CATEGORY                       #
#####################################################
def classify(posting, provider=None, model=None):
    """
    Returns a JobCategory. Raises whatever the provider SDK raises - the
    caller decides whether one failed posting should stop the run.
    """
    provider = (provider or os.getenv("LLM_PROVIDER") or "openai").lower()
    model = model or os.getenv("CLASSIFIER_MODEL") or DEFAULT_MODELS.get(provider)

    if model is None:
        raise ValueError(
            f"Unknown provider {provider!r}. Set LLM_PROVIDER to 'openai' or "
            f"'anthropic', or pass --provider."
        )

    user_text = build_user_text(posting)

    if provider == "openai":
        return _classify_openai(user_text, model)
    if provider == "anthropic":
        return _classify_anthropic(user_text, model)

    raise ValueError(f"Unknown provider {provider!r}. Use 'openai' or 'anthropic'.")
