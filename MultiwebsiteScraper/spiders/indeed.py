import scrapy


class IndeedSpider(scrapy.Spider):
    name = "indeed"
    allowed_domains = ["indeed.com"]
    start_urls = ["https://indeed.com"]

    def parse(self, response):
        pass
