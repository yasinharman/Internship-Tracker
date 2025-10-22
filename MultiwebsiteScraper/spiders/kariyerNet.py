import scrapy
from scrapy_playwright.page import PageMethod
from scrapy.loader import ItemLoader
from random import *


class KariyernetSpider(scrapy.Spider):
    name = "kariyerNet"
    allowed_domains = ["asd.com"]
    start_urls = ["https://asd.com"]

    def parse(self, response):
        pass
