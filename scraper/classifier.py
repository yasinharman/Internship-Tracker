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

ONE LOCAL MODEL
---------------
The model runs on this machine, behind Ollama: no API bill, and no posting
leaves the computer. gemma4:12b was chosen by measurement on 21.09.2026 -
docs/pipeline.md, "A local model on the 70 labelled rows".

Ollama speaks OpenAI's chat API, so the openai SDK is the client. The OpenAI
and Anthropic paths that used to sit beside it were removed the same day.
They existed so that the provider could be chosen by measurement, and it has
been; git history has them if an API model is ever to be compared again.
Comparing local models needs neither: tools/eval_classifier.py measures one
against the stored verdicts, and pipeline/classify_jobs.py --compare runs
several over the same postings.

    CLASSIFIER_MODEL   default gemma4:12b - `ollama pull` it first
    CLASSIFIER_URL     default Ollama on this machine
"""

import logging
import os

from pydantic import BaseModel
from typing import Literal

from . import fields as fields_module
from .fields import FIELDS

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemma4:12b"

# How much of the description is worth sending. The title decides most cases;
# the description is there to break ties ("Stajyer" at a software house). Full
# descriptions run to several thousand characters of boilerplate about company
# culture, which costs tokens and adds nothing.
DESCRIPTION_CHARS = 1500

# The local server, and what every request to it carries besides the prompt.
# Left to itself, the server uses each model's own defaults: Gemma 4 and
# Qwen3.5 reason before answering unless told not to, and each ships its own
# temperature. LOCAL_REQUEST is the request the model was measured with -
# tools/eval_classifier.py imports this dict rather than keeping a copy, so
# what was measured is what runs.
LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"
LOCAL_REQUEST = {"temperature": 0, "reasoning_effort": "none"}


#####################################################
# WHAT COMES BACK                                   #
#####################################################
# The slugs as an enum rather than free text: Ollama is given the list in the
# response schema, so a field it has not been offered cannot come back at all.
# fields.clean() is still the belt to this brace - the schema is enforced by
# the server, and the server is a local process we restart.
FieldSlug = Literal[tuple(FIELDS)]      # type: ignore[valid-type]


class PostingFields(BaseModel):
    fields: list[FieldSlug]
    is_internship: bool
    reason: str          # one sentence, Turkish - shown in the dashboard


#####################################################
# THE PROMPT                                        #
#####################################################
# Any edit to it is a new experiment: tools/eval_classifier.py records its
# hash, and the model choice was measured on this exact text.
_FIELD_LINES = "\n".join(f"- {slug}: {label}" for slug, label in FIELDS.items())

SYSTEM_PROMPT = f"""\
Sen bir staj ilanı sınıflandırıcısısın. Sana bir iş ilanı verilecek. İki soruya \
cevap vereceksin.

1) `fields`: Bu ilan hangi bölümdeki öğrenciye uygun? Aşağıdaki listeden EN AZ \
   BİR, EN FAZLA ÜÇ alan seç. İlk yazdığın alan ilanın asıl alanı olsun.

{_FIELD_LINES}

Kurallar:
- Sadece yukarıdaki anahtarları yaz; başka bir kelime yazma.
- İlan birden fazla bölüme açıksa hepsini yaz. Örnek: "Yazılım ve Veri \
  Stajyeri" -> ["yazilim", "veri_yapay_zeka"].
- İlan hangi departmanda çalışılacağını SÖYLEMİYORSA ve şirket geneline açık \
  bir staj/yetenek programıysa yalnızca ["genel_program"] yaz.
- Listedeki hiçbir alana uymuyorsa yalnızca ["diger"] yaz.
- "genel_program" ve "diger" tek başına yazılır, başka alanla birlikte yazılmaz.
- Öğrencinin bölümüne göre seç, şirketin sektörüne göre değil. Bir bankanın \
  yazılım stajı "yazilim"dır, "finans_muhasebe" değil.

2) `is_internship`: İlan bir STAJ ilanıysa true yaz. Tam zamanlı bir iş, \
   yarı zamanlı bir iş, çırak/kalfa ilanı ya da staj olmayan başka bir şeyse \
   false yaz. Emin değilsen true yaz: yanlış eleme gerçek bir fırsatı \
   kaybettirir, fazladan görünen bir ilan sadece bir satır gürültüdür.

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
# ONE POSTING -> ITS FIELDS                         #
#####################################################
def classify(posting, model=None):
    """
    Returns a PostingFields whose `fields` have been through fields.clean().

    Raises whatever the openai SDK raises - a connection error when Ollama is
    not running, a 404 when the model has not been pulled - and the caller
    decides whether one failed posting should stop the run.
    """
    from openai import OpenAI

    model = model or os.getenv("CLASSIFIER_MODEL") or DEFAULT_MODEL

    # Its own client with a throwaway key, not the SDK's defaults: those read
    # OPENAI_API_KEY and OPENAI_BASE_URL from the environment, and an older
    # .env still holds a real key. The local server ignores the key, and a
    # wrong URL is refused rather than billed.
    client = OpenAI(
        base_url=os.getenv("CLASSIFIER_URL") or LOCAL_BASE_URL,
        api_key="local",
    )

    # The SDK moved this off the `beta` namespace; both spellings are still in
    # the wild, so take whichever this installation has.
    parse = getattr(client.chat.completions, "parse", None)
    if parse is None:
        parse = client.beta.chat.completions.parse

    completion = parse(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_text(posting)},
        ],
        response_format=PostingFields,
        **LOCAL_REQUEST,
    )
    answer = completion.choices[0].message.parsed
    return PostingFields(
        fields=fields_module.clean(answer.fields if answer else []),
        is_internship=True if answer is None else bool(answer.is_internship),
        reason=(answer.reason if answer else "") or "",
    )
