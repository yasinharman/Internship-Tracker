# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy
from itemloaders.processors import MapCompose, TakeFirst, Join

def clean_up_n(txt):
    try:
        txt = txt.replace("\n", "")
        txt = txt.strip()
        return txt
    except:
        return txt

# Metinlerdeki gereksiz boşlukları temizlemek için yardımcı fonksiyon
def compress_whitespace(text):
    if text:
        return ' '.join(text.split())
    return text

class KariyerNetItem(scrapy.Item):

    job_title = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    company = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    location = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    job_type = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    job_description = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    url = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    source_site = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )

class TechCareerItem(scrapy.Item):

    job_title = scrapy.Field(
        output_processor = TakeFirst()
    )
    company = scrapy.Field(
        output_processor = TakeFirst()
    )
    location = scrapy.Field(
        output_processor = TakeFirst()
    )
    work_method = scrapy.Field(
        output_processor = TakeFirst()
    )
    experience = scrapy.Field(
        output_processor = TakeFirst()
    )

class IndeedItem(scrapy.Item):
    job_title = scrapy.Field(
        output_processor = TakeFirst()
    )
    company = scrapy.Field(
        output_processor = TakeFirst()
    )
    location = scrapy.Field(
        output_processor = TakeFirst()
    )
    job_type = scrapy.Field(
        output_processor = TakeFirst()
    )
    job_description = scrapy.Field(
        input_processor=MapCompose(compress_whitespace),
        output_processor=Join(' ')
    )
    url = scrapy.Field(
        output_processor = TakeFirst()
    )
    source_site = scrapy.Field(
        output_processor = TakeFirst()
    )