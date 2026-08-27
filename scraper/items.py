# Define here the models for your scraped items
import scrapy

class JobPostItem(scrapy.Item):
    
    '''
    Only created data fields in here,
    data normalization process is done in loaders.py
    '''
    job_title = scrapy.Field()
    company = scrapy.Field()
    location = scrapy.Field()
    job_type = scrapy.Field()
    job_description = scrapy.Field()
    url = scrapy.Field()
    source_site = scrapy.Field()