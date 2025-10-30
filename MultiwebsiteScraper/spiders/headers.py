import scrapy

class HeadersSpider(scrapy.Spider):
    name = 'headers'
    allowed_domains = ['httpbin.io']
    start_urls = ['https://httpbin.io/user-agent']

    def parse(self, response):
        self.log(f'RESPONSE: {response.body}')
