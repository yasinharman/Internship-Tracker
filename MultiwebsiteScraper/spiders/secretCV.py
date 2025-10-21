import scrapy


class SecretcvSpider(scrapy.Spider):
    name = "secretCV"
    allowed_domains = ["asd.com"]
    start_urls = ["https://asd.com"]

    def parse(self, response):
        pass
