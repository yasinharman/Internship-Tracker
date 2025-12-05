import scrapy
import json

class JoobleSpider(scrapy.Spider):
    name = "jooble"
    api_url = "https://tr.jooble.org/api/serp/jobs"

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
        'HTTPCACHE_DIR' : 'httpcache_linkedin',

        # 4. Hata kodlarını cache'leme!
        # Eğer site sana 403 (Ban), 404 veya 500 hatası verirse bunu kaydetmesin.
        # Kaydederse, hatayı düzeltip tekrar çalıştırdığında bile yine o hatayı okursun.
        'HTTPCACHE_IGNORE_HTTP_CODES' : [400, 401, 403, 404, 429, 500, 503],

        # 5. Standart dosya sistemi depolamasını kullan (Varsayılan budur ama yazmakta fayda var)
        'HTTPCACHE_STORAGE' : 'scrapy.extensions.httpcache.FilesystemCacheStorage'
    }

    def start_requests(self):

        headers = {
            "Content-Type": "application/json",
        }
        payload = {
            "page": 1,
            "region": "İstanbul",
            "search": "python",
            "regionId": 56560
        }

        yield scrapy.http.JsonRequest(
            url=self.api_url,
            data=payload,
            headers=headers,
            callback=self.parse
        )

    def parse(self, response):
            try:
                data = json.loads(response.text)
            except json.JSONDecodeError:
                self.logger.error("JSON parse edilemedi!")
                return

            jobs = data.get('jobs', [])
            
            if not jobs:
                self.logger.info("No more job applications.")
                return 

            for job in jobs:
                yield {'url': job.get('url')}

            current_page = response.meta['page_num']
            
            next_page = current_page + 1
            
            new_payload = {
                "page": next_page,
                "region": "İstanbul",
                "search": "python",
                "regionId": 56560
            }

            yield scrapy.http.JsonRequest(
                url=self.api_url,
                data=new_payload,
                callback=self.parse,
                meta={'page_num': next_page}
            )


class DetailWorkerSpider(scrapy.Spider):
    name = "detail_worker"

    def start_requests(self):
        # Dosya yolu
        file_path = 'urller.jsonl'
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                
                for line_number, line in enumerate(f):
                    
                    if not line.strip():
                        continue
                        
                    try:
                        item = json.loads(line)
                        url = item.get('url')
                        
                        if url:
                            yield scrapy.Request(url=url, callback=self.parse_detail)
                            
                    except json.JSONDecodeError:
                        self.logger.warning(f"{line_number}. satırda bozuk JSON verisi var, atlanıyor.")
                        
        except FileNotFoundError:
            self.logger.error("Dosya bulunamadı! Lütfen önce collector'ı çalıştır.")

    def parse_detail(self, response):
        yield {
            'baslik': response.css('h1::text').get(),
            'url': response.url
        }
