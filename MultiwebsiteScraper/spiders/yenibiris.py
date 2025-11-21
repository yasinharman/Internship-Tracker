import scrapy


class YenibirisSpider(scrapy.Spider):
    name = "yenibiris"
    start_url = "https://www.yenibiris.com/is-ilanlari/istanbul-avrupa-yakasi+bilisim-internet"

    def parse(self, response):
        pass
