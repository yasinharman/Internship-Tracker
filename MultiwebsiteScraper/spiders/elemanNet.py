import scrapy


class ElemannetSpider(scrapy.Spider):
    name = "elemanNet"
    allowed_domains = ["asd.com"]
    start_urls = ["https://asd.com"]

    def parse(self, response):
        pass
