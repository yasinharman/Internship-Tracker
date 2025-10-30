# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy
from itemloaders.processors import MapCompose, TakeFirst

class MultiwebsitescraperItem(scrapy.Item):
    # define the fields for your item here like:
    # name = scrapy.Field()
    pass

def clean_up_n(txt):
    try:
        txt = txt.replace("\n", "")
        txt = txt.strip()
        return txt
    except:
        return txt

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
    wfh = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    work_method = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    experience = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    department = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )
    appointment_count = scrapy.Field(
        input_processor=MapCompose(clean_up_n),
        output_processor=TakeFirst()
    )