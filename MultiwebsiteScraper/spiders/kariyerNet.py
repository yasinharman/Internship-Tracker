import scrapy


class KariyernetSpider(scrapy.Spider):
    name = "kariyerNet"
    allowed_domains = ["asd.com"]
    start_urls = ["https://asd.com"]

    def parse(self, response):
        pass
