import scrapy


class JoobleSpider(scrapy.Spider):
    name = "jooble"
    allowed_domains = ["jooble.com"]
    start_urls = ["https://jooble.com"]

    def parse(self, response):
        pass
