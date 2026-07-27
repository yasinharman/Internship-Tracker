from itemadapter import ItemAdapter
from sqlalchemy.orm import sessionmaker
from .models import JobPost, db_connect, create_table
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
                existing_job.job_description = item.get('job_description')
                existing_job.job_type = normalized_job_type

                existing_job.is_active = True

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
                