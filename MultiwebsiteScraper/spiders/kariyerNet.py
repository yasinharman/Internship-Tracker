import scrapy
from urllib.parse import urlencode
from ..loaders import KariyerNetLoader

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
            # --- DEBUG VE CACHE AYARLARI ---

    # 1. Cache'i aktif hale getirir
    'HTTPCACHE_ENABLED' : True,

    # 2. Cache süresi (Saniye cinsinden). 
    # '0' yaparsan sonsuza kadar saklar (silene kadar).
    'HTTPCACHE_EXPIRATION_SECS' : 0,

    # 3. Cache dosyalarının saklanacağı klasör adı.
    # Proje ana dizininde 'httpcache' adında bir klasör oluşacak.
    'HTTPCACHE_DIR' : 'httpcache_kariyer',

    # 4. Hata kodlarını cache'leme!
    # Eğer site sana 403 (Ban), 404 veya 500 hatası verirse bunu kaydetmesin.
    # Kaydederse, hatayı düzeltip tekrar çalıştırdığında bile yine o hatayı okursun.
    'HTTPCACHE_IGNORE_HTTP_CODES' : [400, 401, 403, 404, 429, 500, 503],

    # 5. Standart dosya sistemi depolamasını kullan (Varsayılan budur ama yazmakta fayda var)
    'HTTPCACHE_STORAGE' : 'scrapy.extensions.httpcache.FilesystemCacheStorage'
    }

    def get_kariyer_search_url(self, city_plate_number, keyword, page_num):
        parameters = {"ct": city_plate_number, "kw": keyword, "cp":page_num}
        return "https://www.kariyer.net/is-ilanlari?" + urlencode(parameters)


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
                            'sops_render_js': True,  # İş ilanlarının listelendiği ilk sayfada bot korumasını bypass edebilmek için js render yapıyoruz.
                            'sops_country': 'tr'
                        }
                    )
    
    def parse_job_links(self, response):
        container = response.css("div.list-items-wrapper")
        job_links = container.css("div[data-test='list-items']")

        for job_link in job_links:
            link = job_link.css("div[data-test='ad-card'] a[data-test='ad-card-item']::attr(href)").get()
            yield scrapy.Request(
                url = response.urljoin(link),
                callback=self.parse_detail,
                meta={
                    'sops_render_js': False, # İlan detaylarının olduğu sayfada antibot koruması çok yoğun olmadığından API kredisi tasarrufu ve hız için bu sayfalarda js render yapmıyoruz.
                    'sops_residential': False,
                    'sops_country': 'tr',
                }
            )

    def parse_detail(self, response):

        DEFAULT_VALUE = "N/A"
        loader = KariyerNetLoader(response=response)

        loader.add_css("job_title", "div[data-test='job-title']::text", default=DEFAULT_VALUE)
        
        loader.add_css("company", "a[data-test='company-name']::text", default=DEFAULT_VALUE)
        
        loader.add_css("location", "span[data-test='company-location']::text", default=DEFAULT_VALUE)
        
        loader.add_css("job_type", 'p[data-test="detail-work-type"]::text', default=DEFAULT_VALUE)
        
        loader.add_xpath('job_description', '//div[@data-test="qualifications-and-job-description"]//text()')
        
        loader.add_value("url", response.url)
        
        loader.add_css("source_site", 'kariyernet')

        yield loader.load_item()

