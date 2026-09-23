from sqlalchemy.orm import sessionmaker
from .models import JobPost, db_connect, create_table
from datetime import datetime
import re

########################################
# JOB TYPE DATA NORMALIZATION MAPPING TABLE #
########################################
JOB_TYPE_MAPPING = {
    # Full-Time Aliases
    'full-time': 'Full-Time',
    'fulltime': 'Full-Time',
    'full time': 'Full-Time',
    'tam zamanlı': 'Full-Time',
    'tamzamanlı': 'Full-Time',
    'tam-zamanlı': 'Full-Time',
    'ft': 'Full-Time',
    'permanent': 'Full-Time',
    'permanent job': 'Full-Time',
    'sürekli': 'Full-Time',
    
    # Part-Time Aliases
    'part-time': 'Part-Time',
    'parttime': 'Part-Time',
    'part time': 'Part-Time',
    'yarı zamanlı': 'Part-Time',
    'yarızamanlı': 'Part-Time',
    'yarı-zamanlı': 'Part-Time',
    'pt': 'Part-Time',
    
    # Internship Aliases
    'internship': 'Internship',
    'intern': 'Internship',
    'staj': 'Internship',
    'stajyerlik': 'Internship',
    'stajyer': 'Internship',
    
    # Contract Aliases
    'contract': 'Contract',
    'contract work': 'Contract',
    'kontrat': 'Contract',
    'sözleşmeli': 'Contract',
    'sözleşmeli çalışan': 'Contract',
    'temporary': 'Contract',
    'freelance': 'Freelance',
    'freelancer': 'Freelance',
    'serbest zamanlı': 'Freelance',
    'geçici': 'Temporary',
    'proje bazlı': 'Contract',
    
    # Remote Work
    'remote': 'Remote',
    'remote work': 'Remote',
    'uzaktan çalışma': 'Remote',
    'uzaktan': 'Remote',
    'uzaktan / remote': 'Remote',
}

###########################################################
# WHICH CATEGORY WINS WHEN ONE STRING MATCHES SEVERAL     #
###########################################################
'''
    "Staj / Tam Zamanlı" matches both Internship and Full-Time. We keep the
    more specific label, and the ones being filtered on (Internship,
    Part-Time) sit at the top on purpose: an ambiguous posting is better shown
    than silently dropped.
'''
CATEGORY_PRIORITY = [
    "Internship", "Part-Time", "Freelance", "Temporary", "Contract",
    "Full-Time",
    # Remote is last because it describes WHERE the work happens, not the
    # employment type. "Tam Zamanlı, Uzaktan" is a full-time job that happens
    # to be remote, so Full-Time is the more honest label for this column.
    "Remote",
]

# Two-letter aliases only ever match exactly. As substrings they are
# everywhere: 'ft' inside "Draft"/"Software", 'pt' inside "Adaptasyon".
EXACT_ONLY_ALIASES = {"ft", "pt"}


#########################################################
# TURKISH-AWARE LOWERCASING                             #
#########################################################
def turkish_lower(text):
    """
    str.lower() gets Turkish wrong: "YARI ZAMANLI".lower() is "yari zamanli"
    with a dotted i, which never matches the "yarı zamanlı" key.
    """
    return text.replace("I", "ı").replace("İ", "i").lower()


def _flatten(text):
    """Flatten every separator so 'Part-Time', 'part_time' and 'Part Time'
    all become the same string."""
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def canonical_forms(text):
    """
    Both lowercasings, because neither is right on its own: Turkish rules turn
    "YARI" into the "yarı" we need but also turn "TIME" into "tıme", which
    matches nothing. Turkish job types routinely mix the two languages
    ("PART-TIME", "YARI ZAMANLI"), so we produce both readings and let a match
    on either one count.
    """
    forms = []
    for lowered in (turkish_lower(text), text.lower()):
        flat = _flatten(lowered)
        if flat and flat not in forms:
            forms.append(flat)
    return forms


def canonical(text):
    """Single canonical form - only used to normalize the alias table itself,
    which is already written in lowercase Turkish."""
    return _flatten(turkish_lower(text))


# Canonical form of every alias, longest first so the most specific alias is
# tested before a shorter one that happens to be contained in it.
CANONICAL_MAPPING = {canonical(alias): value for alias, value in JOB_TYPE_MAPPING.items()}
SEARCHABLE_ALIASES = sorted(
    (alias for alias in CANONICAL_MAPPING if alias not in EXACT_ONLY_ALIASES),
    key=len,
    reverse=True,
)


###################################################
# NORMALIZING THE JOB TYPE BY USING THIS FUNCTION #
###################################################
def normalize_job_type(job_type):
    """
    Sites decorate the job type freely: "Stajyer (Uzaktan)", "Staj / Intern",
    "Part-time (Hafta sonu)". Exact-match lookup sent all of those to "Other",
    which was merely untidy while we showed everything - but becomes data loss
    now that we filter on this column. So: exact match first, then a
    word-boundary search for a known alias anywhere in the string.
    """
    if not job_type or not isinstance(job_type, str):
        return "Other"

    forms = canonical_forms(job_type)
    if not forms:
        return "Other"

    # Fast path: the whole value is a known alias.
    for form in forms:
        if form in CANONICAL_MAPPING:
            return CANONICAL_MAPPING[form]

    # Otherwise look for an alias inside the string. Lookarounds rather than
    # \b so multi-word aliases ("yarı zamanlı") behave too.
    matched = set()
    for alias in SEARCHABLE_ALIASES:
        pattern = rf"(?<!\w){re.escape(alias)}(?!\w)"
        for form in forms:
            if re.search(pattern, form, flags=re.UNICODE):
                matched.add(CANONICAL_MAPPING[alias])
                break

    for category in CATEGORY_PRIORITY:
        if category in matched:
            return category

    return "Other"

#################################
# PIPELINE TO POSTGRES DATABASE #
#################################
# What a spider sends when it has no description to send. Spelled out here
# rather than imported: it is BaseApiSpider.DEFAULT_VALUE (scraper/api_spider.py),
# a class attribute rather than a module constant, and importing the spider
# base class into the pipeline to read one string is a heavier coupling than
# the duplication. If that value ever changes, this is the other place.
NO_DESCRIPTION = "N/A"


class JobScraperPipeline:
    def __init__(self):
        engine = db_connect()

        create_table(engine)
        self.Session = sessionmaker(bind=engine)

    def process_item(self, item, spider):

        session = self.Session()

        try:
            # Job type normalization
            normalized_job_type = normalize_job_type(item.get('job_type'))
            
            # If the job application is already in the database we are updating its data if there is any difference
            existing_job = session.query(JobPost).filter_by(url=item.get('url')).first()

            if existing_job:
                existing_job.job_title = item.get('job_title')
                existing_job.company = item.get('company')
                existing_job.location = item.get('location')
                # NOT unconditional, unlike the fields around it. The check
                # spiders now write this column too (scraper/openings.py), and
                # they are the only source of a description for LinkedIn and
                # Indeed - whose cards spiders send the literal "N/A" because
                # a real one would cost an extra request per posting.
                #
                # Overwriting with that would erase a description the checks
                # paid for, on every single re-crawl, and the classifier would
                # be back to reading titles without anything saying so.
                #
                # Since 21.09.2026 that is every site: no cards spider opens a
                # posting page any more, so all of them send "N/A" and the
                # checks are the only writer of a real description.
                incoming = item.get('job_description')
                if incoming and incoming != NO_DESCRIPTION:
                    existing_job.job_description = incoming

                # The same guard, for the same reason. techcareer's list
                # record has no working-type field (docs/sites/techcareer.md,
                # 21.09.2026), so a posting whose title names no type arrives
                # as "N/A" and normalises to "Other". Writing that back would
                # turn a stored "Part-Time" into "Other" on every re-crawl and
                # drop it from the board's default view without a word.
                if item.get('job_type') and item.get('job_type') != NO_DESCRIPTION:
                    existing_job.job_type = normalized_job_type

                # ONLY WHEN THERE IS ONE, unlike the five fields above.
                #
                # Those five always carry a value - the spiders append
                # DEFAULT_VALUE as a last fallback - so overwriting can never
                # blank them. A logo has no such fallback on purpose, so a
                # card whose image had not lazily loaded, a record the site
                # carries no branding for, or a selector that stopped matching
                # all arrive as nothing at all.
                #
                # Writing that back would DELETE a logo we already have, one
                # row per re-crawl, and a changed selector would drain the
                # board over a single run while every spider still exited 0 -
                # the except below swallows per-item failures, so nothing
                # about it would be loud. This way the failure is "no new
                # logos", which is the same shape as every other nullable
                # column here: NULL means not yet, and the next run retries.
                #
                # The cost is a stale url when an employer changes their
                # logo. The board absorbs that already: CompanyLogo falls back
                # to the company's initials when the image does not load.
                if item.get('company_logo_url'):
                    existing_job.company_logo_url = item.get('company_logo_url')

                # Postings are matched on url, which is UNIQUE - so a posting
                # seen again is an update, never a second row.
                #
                # is_active is NOT reset here when the classifier has already
                # excluded this posting. It used to be set to True
                # unconditionally, from back when nothing ever set it to
                # False. Now the classifier owns the flag: a posting it
                # judged not to be an internship would come back to life
                # every time the crawl saw it again, and stay there, because
                # only rows with job_category IS NULL are ever reclassified.
                #
                # The test was `job_category != "other"` until 23.09.2026,
                # when `other` stopped meaning "hidden" and became one field
                # among two dozen (scraper/fields.py). Being in a field is
                # not a reason to hide anything any more; not being an
                # internship still is.
                if existing_job.is_internship is not False:
                    existing_job.is_active = True

                # The url was in a search result just now, so the posting is
                # open. The *_check spiders read this and nothing else to undo
                # a closed_at they wrote earlier - see models.JobPost. They own
                # closed_at; this side only leaves the evidence, so the two
                # writers never touch the same column.
                existing_job.last_seen_at = datetime.utcnow()

                spider.logger.info(f"Existing job post updated: {item.get('url')}")
            
            # If the job application is not in the database we are adding its data to database
            else:
                new_job = JobPost(
                    job_title = item.get('job_title'),
                    company = item.get('company'),
                    location = item.get('location'),
                    job_description = item.get('job_description'),
                    url = item.get('url'),
                    source_site = item.get('source_site'),
                    job_type = normalized_job_type,
                    company_logo_url = item.get('company_logo_url'),
                    last_seen_at = datetime.utcnow(),
                    # For created_at and is_active fields we created default values
                )
                session.add(new_job)
                spider.logger.info(f"New job application added.")
            
            session.commit()
        
        # Error handling
        except Exception as e:
            session.rollback() # If any error occurs while data was going through pipeline program rolls back the changes to not mess up the database.
            spider.logger.error(f"Some error occured while job application was being added to database: {e}")
        
        # We are ending the session to not keep our database busy
        finally:
            session.close() # To prevent "Too many connections error"
        
        # We are returning the item to see the data on the terminal
        return item
                