import scrapy
from urllib.parse import urlencode
from scrapy.loader import ItemLoader
from MultiwebsiteScraper.items import IndeedItem

class IndeedJobSpider(scrapy.Spider):
    name = "indeed_html"

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
        'HTTPCACHE_DIR' : 'httpcache_indeed',

        # 4. Hata kodlarını cache'leme!
        # Eğer site sana 403 (Ban), 404 veya 500 hatası verirse bunu kaydetmesin.
        # Kaydederse, hatayı düzeltip tekrar çalıştırdığında bile yine o hatayı okursun.
        'HTTPCACHE_IGNORE_HTTP_CODES' : [400, 401, 403, 404, 429, 500, 503],

        # 5. Standart dosya sistemi depolamasını kullan (Varsayılan budur ama yazmakta fayda var)
        'HTTPCACHE_STORAGE' : 'scrapy.extensions.httpcache.FilesystemCacheStorage'
    }

    def get_indeed_search_url(self, keyword, location, offset=0):
        parameters = {"q": keyword, "l": location, "filter": 0, "start": offset}
        return "https://tr.indeed.com/jobs?" + urlencode(parameters)
    
    def start_requests(self):
        keyword_list = ['python']
        location_list = ['istanbul']
        
        page_limit = 3

        for keyword in keyword_list:
            for location in location_list:
                # Sayfa Döngüsü (Pagination Mantığı Burada)
                for page in range(page_limit):
                    offset = page * 10
                    
                    indeed_jobs_url = self.get_indeed_search_url(keyword, location, offset)
                    
                    yield scrapy.Request(
                        url=indeed_jobs_url, 
                        callback=self.parse_job_links, 
                        meta={
                            'keyword': keyword,
                            'location': location,
                            'offset': offset,
                            'page_num': page + 1,
                            'sops_render_js': True, # İş ilanlarının listelendiği ilk sayfada bot korumasını bypass edebilmek için js render yapıyoruz.
                        }
                    )
    
    def parse_job_links(self, response):
        container = response.css("div#mosaic-provider-jobcards")
        
        all_jobs = container.css("div.job_seen_beacon")

        for job in all_jobs:
            link = job.css("h2.jobTitle a::attr(href)").get()
            
            if link:
                yield scrapy.Request(
                    url = response.urljoin(link),
                    callback = self.parse_job_detail,
                    meta = {
                        'sops_render_js': False, # İlan detaylarının olduğu sayfada antibot koruması çok yoğun olmadığından API kredisi tasarrufu ve hız için bu sayfalarda js render yapmıyoruz.
                        'sops_residential': True,
                        'sops_country': 'tr',
                    }
                )

    def parse_job_detail(self, response):
        container = response.css("div.jobsearch-JobComponent")

        DEFAULT_VALUE = "N/A"
        loader = ItemLoader(item=IndeedItem(), selector=container)

        loader.add_css("job_title", "h1[data-testid='jobsearch-JobInfoHeader-title'] span::text", default=DEFAULT_VALUE)
        
        loader.add_css("company", "div[data-testid='inlineHeader-companyName'] a::text", default=DEFAULT_VALUE)
        loader.add_css("company", "div[data-testid='inlineHeader-companyName']::text", default=DEFAULT_VALUE)
        
        loader.add_css("location", "div[data-testid='jobsearch-JobInfoHeader-companyLocation'] span::text", default=DEFAULT_VALUE)
        loader.add_css("location", "div[data-testid='jobsearch-JobInfoHeader-companyLocation']::text", default=DEFAULT_VALUE)
        
        loader.add_css("job_type", "div#jobDetailsSection div[aria-label='İş türü'] span::text", default=DEFAULT_VALUE)
        
        loader.add_xpath('job_description', '//div[@id="jobDescriptionText"]//text()')

        loader.add_value('source_site', 'linkedin')

        yield loader.load_item()

