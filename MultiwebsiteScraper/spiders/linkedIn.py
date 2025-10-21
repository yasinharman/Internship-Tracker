import scrapy


class LinkedinSpider(scrapy.Spider):
    name = "linkedIn"
    allowed_domains = ["asd.com"]
    start_urls = ["https://asd.com"]

    def parse(self, response):
        pass
