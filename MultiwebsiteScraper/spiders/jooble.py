###############
# ADD API KEY #
###############

import scrapy
import json
from ..loaders import JoobleLoader
import os
from scrapy.http import JsonRequest
###############
# MAIN SPIDER #
###############

class JoobleUrlCrawler(scrapy.Spider):
    name = "jooble"
    # API URL yerine normal arama URL'si kullanıyoruz
    base_url = "https://tr.jooble.org/SearchResult?rgns=İstanbul&ukw=python"

    custom_settings = {
        'FEEDS': {
            'urller.jsonl': {
                'format': 'jsonlines',
                'encoding': 'utf8',
                'overwrite': True,
            }
        },
        'SCRAPEOPS_API_KEY': "ba7852f0-91f8-4d4b-b1bc-dcccd26e2368",
        'SCRAPEOPS_PROXY_ENABLED': True,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapeops_scrapy_proxy_sdk.scrapeops_scrapy_proxy_sdk.ScrapeOpsScrapyProxySdk': 725,
        },
        'CONCURRENT_REQUESTS': 1,
        'DOWNLOAD_DELAY': 3,
    }

    def start_requests(self):
        # POST yerine GET isteği atıyoruz
        yield scrapy.Request(
            url=self.base_url,
            callback=self.parse,
            meta={'page_num': 1}
        )

    def parse(self, response):
        # 1. Yöntem: data-test-name özniteliği üzerinden (En güveniliri)
        job_links = response.css('a[data-test-name="job-link"]::attr(href)').getall()
        
        # 2. Yöntem: Eğer yukarıdaki boş dönerse (Alternatif)
        if not job_links:
            self.logger.info("First selector failed, trying alternative...")
            job_links = response.css('section[data-test-name="job-card"] a::attr(href)').getall()

        # 3. Yöntem: En geniş kapsamlı (Her ihtimale karşı)
        if not job_links:
            job_links = response.xpath('//a[contains(@href, "/desc/")]/@href').getall()

        self.logger.info(f"Found {len(job_links)} job links on this page.")

        for link in job_links:
            # Linki tam URL haline getir
            full_url = response.urljoin(link)
            yield {'url': full_url}

        # PAGINATION (Sayfalandırma)
        current_page = response.meta['page_num']
        if current_page < 5:  # Test için ilk 5 sayfa
            next_page = current_page + 1
            next_url = f"{self.base_url}&p={next_page}"
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                meta={'page_num': next_page}
            )
'''
    In the previous spider we parsed the urls from the json 
    now in this spider we will parse the job details inside this urls
'''
class DetailWorkerSpider(scrapy.Spider):
    name = "detail_worker"

    
    ####################################################
    # CUSTOM SETTINGS THAT ONLY ENABLED ON THIS SPIDER #
    ####################################################

    custom_settings = {
        'SCRAPEOPS_API_KEY': "ba7852f0-91f8-4d4b-b1bc-dcccd26e2368", 
        'SCRAPEOPS_PROXY_ENABLED': True,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapeops_scrapy_proxy_sdk.scrapeops_scrapy_proxy_sdk.ScrapeOpsScrapyProxySdk': 725,
        },
        'CONCURRENT_REQUESTS': 1, 
        'DOWNLOAD_DELAY': 2,
        
        'DEFAULT_REQUEST_HEADERS': {
                    'Accept': 'application/json',
                    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                },
        
    ##############################################
    # DEBUG AND CACHE SETTINGS FOR THE TEST RUNS #
    ##############################################

    # ENABLES THE CACHE #
    'HTTPCACHE_ENABLED' : False,

    # CACHE TIME (Seconds) #
    # '0' MEANS IT WILL BE STORED FOREVER #
    'HTTPCACHE_EXPIRATION_SECS' : 0,

    # NAME OF THE STORAGE FILE FOR THE CACHE FILES #
    'HTTPCACHE_DIR' : 'httpcache_linkedin',

    # WE ARE ONLY TAKING THE RESULTS OF THE SUCCESFUL REQUESTS #
    'HTTPCACHE_IGNORE_HTTP_CODES' : [400, 401, 403, 404, 429, 500, 503],

    # USE DEFAULT FILE SYSTEM STORAGE #
    'HTTPCACHE_STORAGE' : 'scrapy.extensions.httpcache.FilesystemCacheStorage',

    # ENSURES THAT WE ARE NOT USING API CREDITS FOR THE SAME URL WITH DIFF. HEADERS.
    'HTTPCACHE_IGNORE_HEADERS': ['Set-Cookie', 'X-Scrapeops-Id', 'X-Proxy-Id'],

    #TO PREVENT SAME URL'S WITH DIFFERENT PARAMETERS
    'HTTPCACHE_POLICY': 'scrapy.extensions.httpcache.DummyPolicy',
    }


    ###################################################################
    # SENDING REQUESTS TO THE URL LIST THAT WE GET FROM THE JSON TEXT #
    ###################################################################

    def start_requests(self):
        # FILE PATH
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
                            yield scrapy.Request(
                                        url=url, 
                                        callback=self.parse_detail
                                        )
                            
                    except json.JSONDecodeError:
                        self.logger.warning(f"{line_number}. There is broken JSON data on the line, passing the line.")
                        
        except FileNotFoundError:
            self.logger.error("File not found. Run the collector first.")

    
    #######################################
    # PARSING THE JOB APPLICATION DETAILS #
    #######################################

    def parse_detail(self, response):
        
        DEFAULT_VALUE = "N/A"
        loader = JoobleLoader(response=response)

        
        loader.add_css("job_title", "div[data-test-name='_jdpHeaderBlock'] h1::text", default=DEFAULT_VALUE)
        
        loader.add_css("company", "p[data-test-name='_companyName']::text", default=DEFAULT_VALUE)
        
        loader.add_css("location", "a[data-test-name='_regionLink'] span::text", default=DEFAULT_VALUE)
        
        loader.add_xpath("job_type", "//div[@class='caption']/text()", default=DEFAULT_VALUE)

        loader.add_css("job_description", "div[data-test-name='_jobDescriptionBlock'] *::text", default=DEFAULT_VALUE)

        loader.add_value("url", response.url)

        loader.add_value("source_site", "jooble.com")

        yield loader.load_item()       

