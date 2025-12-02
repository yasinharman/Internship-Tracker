import scrapy
from urllib.parse import urlencode
from scrapy.loader import ItemLoader
from MultiwebsiteScraper.items import KariyerNetItem # ITEM AYARLAMASI YAPILACAK
from random import randint
from pathlib import Path

class KariyernetSpider(scrapy.Spider):
    name = "kariyerNet"

    custom_settings = {
    'SCRAPEOPS_API_KEY': '', 
    'SCRAPEOPS_PROXY_ENABLED': True,
    'DOWNLOADER_MIDDLEWARES': {
        'scrapeops_scrapy_proxy_sdk.scrapeops_scrapy_proxy_sdk.ScrapeOpsScrapyProxySdk': 725,
    },
    'CONCURRENT_REQUESTS': 1, 
    'DOWNLOAD_DELAY': 2,
    
    'DEFAULT_REQUEST_HEADERS': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            },
    }

    def get_kariyer_search_url(self, city_plate_number, keyword, page_num):
        parameters = {"ct": city_plate_number, "kw": keyword, "cp":page_num}
        return "https://www.kariyer.net/is-ilanlari/istanbul+avrupa?" + urlencode(parameters)


    def start_requests(self):
        city_plate_list = ["34"]
        keyword_list = ["python"]
        
        page_limit = 3
        
        for city_plate_number in city_plate_list:
            for keyword in keyword_list:
                for page in range(page_limit):
                    page_num = page + 1

                    kariyer_url = self.get_kariyer_search_url(city_plate_number, keyword, page_num)

                    yield scrapy.Request(
                        url=kariyer_url, 
                        callback=self.parse_job_links, 
                        meta={
                            'sops_render_js': True, # İş ilanlarının listelendiği ilk sayfada bot korumasını bypass edebilmek için js render yapıyoruz.
                        })
    def parse_job_links():
        ...

    def parse_detail(self, response):
        container = response.css("div.main-container")

        DEFAULT_VALUE = "N/A"
        loader = ItemLoader(item=KariyerNetItem(), selector=container)

        loader.add_css("job_title", "div[data-test='job-title']::text", default=DEFAULT_VALUE)
        loader.add_css("company", "a[data-test='company-name']::text", default=DEFAULT_VALUE)
        loader.add_css("location", "span[data-test='company-location']::text", default=DEFAULT_VALUE)
        loader.add_css("work_method", 'p[data-test="detail-work-type"]::text', default=DEFAULT_VALUE)
        loader.add_css("experience", 'p[data-test="detail-experience-level"]::text', default=DEFAULT_VALUE)
        loader.add_css("department", 'p[data-test="detail-department-info"]::text', default=DEFAULT_VALUE)
        loader.add_css("appointment_count", 'div.detail:nth-child(4) p::text', default=DEFAULT_VALUE)

        yield loader.load_item()

