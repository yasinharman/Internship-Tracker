import scrapy


class YenibirisSpider(scrapy.Spider):
    name = "yenibiris"
    allowed_domains = ["asd.com"]
    start_urls = ["https://asd.com"]

    def parse(self, response):
        pass
