import scrapy
from ..loaders import LinkedInLoader

# --- BU KISMI EKLE ---
import scrapy.utils.misc
import scrapy.core.scraper

# Scrapy'nin hata veren uyarı fonksiyonunu boş bir fonksiyonla eziyoruz
def warn_on_generator_with_return_value_stub(spider, callable):
    pass

scrapy.utils.misc.warn_on_generator_with_return_value = warn_on_generator_with_return_value_stub
scrapy.core.scraper.warn_on_generator_with_return_value = warn_on_generator_with_return_value_stub
# ---------------------

class LinkedinSpider(scrapy.Spider):
    name = "linkedin"

    custom_settings = {
        'SCRAPEOPS_API_KEY': 'd56d319d-3eb2-4532-b939-a166329c3dda', 
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
        'HTTPCACHE_DIR' : 'httpcache_linkedin',

        # 4. Hata kodlarını cache'leme!
        # Eğer site sana 403 (Ban), 404 veya 500 hatası verirse bunu kaydetmesin.
        # Kaydederse, hatayı düzeltip tekrar çalıştırdığında bile yine o hatayı okursun.
        'HTTPCACHE_IGNORE_HTTP_CODES' : [400, 401, 403, 404, 429, 500, 503],

        # 5. Standart dosya sistemi depolamasını kullan (Varsayılan budur ama yazmakta fayda var)
        'HTTPCACHE_STORAGE' : 'scrapy.extensions.httpcache.FilesystemCacheStorage'
    }

    def get_search_url(self, keyword, location, start):
        url = f"https://tr.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keyword}&location={location}&position=1&pageNum=0&start={start}"
        return url
    
    def start_requests(self):
        keyword_list = ["python"]
        location_list = ["istanbul"]

        jobs_limit = 150
        jobs = 0
        for keyword in keyword_list:
            for location in location_list:
                jobs = 0
                while jobs <= jobs_limit:
                    start = jobs

                    yield scrapy.Request(
                        url = self.get_search_url(keyword, location, jobs),
                        callback = self.get_job_links,
                        meta = {
                            'sops_render_js': False,
                            'sops_country': 'tr',
                        }
                    )
                    jobs += 25

    def get_job_links(self, response):
        all_links = response.css("div.job-search-card")
        for link in all_links:
            job_url = link.css("a.base-card__full-link::attr(href)").get()
            yield scrapy.Request(
                url = job_url,
                callback = self.parse_detail,
                meta = {
                    'sops_render_js': False,
                    'sops_country': 'tr',
                }
            )

    def parse_detail(self, response):

        DEFAULT_VALUE = "N/A"
        loader = LinkedInLoader(response=response)

        loader.add_css("job_title", "h1.top-card-layout__title::text", default=DEFAULT_VALUE)

        loader.add_css("company", "a[data-tracking-control-name='public_jobs_topcard-org-name']::text", default=DEFAULT_VALUE)

        loader.add_css("location", "span.topcard__flavor--bullet::text", default = DEFAULT_VALUE)

        loader.add_xpath("job_type", "//h3[contains(text(), 'İstihdam türü')]/following-sibling::span[contains(@class, 'description__job-criteria-text')]/text()", default=DEFAULT_VALUE)

        loader.add_xpath('job_description', '//div[contains(@class="description__text")]//text()', default=DEFAULT_VALUE)

        loader.add_value("url", response.url)

        loader.add_value('source_site', 'linkedin')

        yield loader.load_item()
        
        