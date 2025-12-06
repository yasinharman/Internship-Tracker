# loaders.py
from scrapy.loader import ItemLoader
from itemloaders.processors import MapCompose, TakeFirst, Join
from .items import JobPostItem

# --- Senin yazdığın Temizlik Fonksiyonları ---
def clean_up_n(txt):
    if txt:
        try:
            txt = txt.replace("\n", "")
            txt = txt.strip()
            return txt
        except:
            return txt
    return txt


def compress_whitespace(text):
    if text:
        return ' '.join(text.split())
    return text


# --- BASE LOADER (Genel Ayarlar) ---
class BaseJobLoader(ItemLoader):
    # Varsayılan olarak tüm veriler JobPostItem kutusuna gidecek
    default_item_class = JobPostItem
    # Varsayılan olarak çıktı alırken listeden ilk elemanı al (TakeFirst)
    default_output_processor = TakeFirst()


class KariyerNetLoader(BaseJobLoader):
    job_title_in = MapCompose(clean_up_n)
    company_in = MapCompose(clean_up_n)
    location_in = MapCompose(clean_up_n)
    job_type_in = MapCompose(clean_up_n)
    url_in = MapCompose(clean_up_n)
    source_site_in = MapCompose(clean_up_n)
    
    job_description_in = MapCompose(clean_up_n, str.strip)
    job_description_out = Join(' ')


class TechCareerLoader(BaseJobLoader):
    
    job_description_in = MapCompose(str.strip, clean_up_n)
    job_description_out = Join(' ')


class IndeedLoader(BaseJobLoader):
    
    job_description_in = MapCompose(compress_whitespace, clean_up_n)
    job_description_out = Join(' ')


class LinkedInLoader(BaseJobLoader):
    
    company_in = MapCompose(compress_whitespace, clean_up_n)
    
    location_in = MapCompose(clean_up_n)
    
    job_description_in = MapCompose(clean_up_n)
    job_description_out = Join(' ')

class JoobleLoader(BaseJobLoader):
    
    job_description_in = MapCompose(compress_whitespace, clean_up_n)
    job_description_out = Join(' ')
