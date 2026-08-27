from scrapy.loader import ItemLoader
from itemloaders.processors import MapCompose, TakeFirst, Join
from .items import JobPostItem

##########################################################
# HELPER FUNCTION TO CLEAN '\n' OPERATORS AND WHITESPACE #
##########################################################
def clean_up_n(txt):
    if txt:
        try:
            txt = txt.replace("\n", "")
            txt = txt.strip()
            return txt
        except:
            return txt
    return txt

#######################################
# HELPER FUNCTION TO CLEAN WHITESPACE #
#######################################
def compress_whitespace(text):
    if text:
        return ' '.join(text.split())
    return text

##################################
# BASE LOADER (GENERAL SETTINGS) #
##################################
class BaseJobLoader(ItemLoader):
    # Varsayılan olarak tüm veriler JobPostItem kutusuna gidecek
    default_item_class = JobPostItem
    # Varsayılan olarak çıktı alırken listeden ilk elemanı al (TakeFirst)
    default_output_processor = TakeFirst()

################################################
# DATA NORMALIZATION SETTINGS FOR 'kariyernet' #
################################################
class KariyerNetLoader(BaseJobLoader):
    job_title_in = MapCompose(clean_up_n)
    company_in = MapCompose(clean_up_n)
    location_in = MapCompose(clean_up_n)
    job_type_in = MapCompose(clean_up_n)
    url_in = MapCompose(clean_up_n)
    source_site_in = MapCompose(clean_up_n)
    
    job_description_in = MapCompose(clean_up_n, str.strip)
    job_description_out = Join(' ')

'''
    TechCareerLoader, IndeedLoader, LinkedInLoader and JoobleLoader used to
    live here, one per DOM-parsing spider. Those spiders are gone: TechCareer
    and Indeed now read embedded JSON and use JsonJobLoader, while LinkedIn and
    Jooble are out of scope entirely (see docs/sites/). Only kariyer.net is
    still parsed from markup, so only its loader remains.
'''

##################################################################
# DATA NORMALIZATION FOR THE JSON API SPIDERS (all sites shared) #
##################################################################
'''
    The DOM loaders above receive a pile of text nodes that have to be
    stitched together. A JSON API hands us one finished value per field, so
    this loader only has to normalize whitespace and pass non-string values
    (ints, bools, nulls) through untouched.

    HTML that arrives inside a JSON field is stripped in api_spider.py by
    strip_html(), before the value ever reaches this loader.
'''
def to_text(value):
    # API fields are not always strings: ids come as ints, flags as booleans.
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    return value

class JsonJobLoader(BaseJobLoader):

    job_title_in = MapCompose(to_text, compress_whitespace)
    company_in = MapCompose(to_text, compress_whitespace)
    location_in = MapCompose(to_text, compress_whitespace)
    job_type_in = MapCompose(to_text, compress_whitespace)
    url_in = MapCompose(to_text, clean_up_n)
    source_site_in = MapCompose(to_text, clean_up_n)

    job_description_in = MapCompose(to_text, compress_whitespace)
    job_description_out = Join(' ')
