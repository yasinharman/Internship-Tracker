###############
# ADD API KEY #
###############

import scrapy
from urllib.parse import urlencode
from ..loaders import IndeedLoader
import os
from dotenv import load_dotenv

load_dotenv()
###############
# MAIN SPIDER #
###############

class IndeedJobSpider(scrapy.Spider):
    name = "indeed_html"

    ####################################################
    # CUSTOM SETTINGS THAT ONLY ENABLED ON THIS SPIDER #
    ####################################################

    custom_settings = {
        'SCRAPEOPS_API_KEY': os.getenv("SCRAPEOPS_API_KEY"), 
        'SCRAPEOPS_PROXY_ENABLED': True,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapeops_scrapy_proxy_sdk.scrapeops_scrapy_proxy_sdk.ScrapeOpsScrapyProxySdk': 725,
        },
        'CONCURRENT_REQUESTS': 4, 
        # 'DOWNLOAD_DELAY': 2,
        
    #     'DEFAULT_REQUEST_HEADERS': {
    #                 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    #                 'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
    # },
        
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

    
    #########################################
    # CREATE THE SEARCH URL FOR THE WEBSITE #
    #########################################

    def get_indeed_search_url(self, keyword, location, offset=0):
        parameters = {"q": keyword, "l": location, "filter": 0, "start": offset}
        return "https://tr.indeed.com/jobs?" + urlencode(parameters)
    

    ############################################
    # TO SEND THE FIRST REQUEST TO THE WEBSITE #
    ############################################

    def start_requests(self):
        keyword_list = ['python']
        location_list = ['istanbul']
        
        page_limit = 3

        for keyword in keyword_list:
            for location in location_list:
                # PAGINATION IS DONE HERE #
                for page in range(page_limit):
                    offset = page * 10
                    
                    indeed_jobs_url = self.get_indeed_search_url(keyword, location, offset)

                    self.logger.info(f"REQUEST IS SENT: {indeed_jobs_url}")
                    
                    yield scrapy.Request(
                        url=indeed_jobs_url, 
                        callback=self.parse_job_links, 
                        meta={
                            'keyword': keyword,
                            'location': location,
                            'offset': offset,
                            'page_num': page + 1,
                            'sops_render_js': True, # WE ARE ENABLING THE JS RENDER OPTION ON THE SOPS SERVICE TO BYPASS ANTIBOT SYSTEM ON THE LINKS PAGE
                            'sops_country': 'tr',
                            'sops_residential': True,
                        }
                    )
    

    #######################################################
    # PARSE ALL JOB LINKS AND SEND REQUEST TO THOSE LINKS #
    #######################################################

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
                        'sops_residential': False,
                        'sops_country': 'tr',
                    }
                )

    ################################################################################################
    # WE ARE PARSING ALL THE USEFUL DATA FROM THE LINKS THAT WE COLLECT FROM THE PREVIOUS FUNCTION # 
    ################################################################################################

    def parse_job_detail(self, response):

        DEFAULT_VALUE = "N/A"
        loader = IndeedLoader(response=response)

        loader.add_css("job_title", "h1[data-testid='jobsearch-JobInfoHeader-title'] span::text", default=DEFAULT_VALUE)
        
        loader.add_css("company", "div[data-testid='inlineHeader-companyName'] a::text", default=DEFAULT_VALUE)
        loader.add_css("company", "div[data-testid='inlineHeader-companyName']::text", default=DEFAULT_VALUE)
        
        loader.add_css("location", "div[data-testid='jobsearch-JobInfoHeader-companyLocation'] span::text", default=DEFAULT_VALUE)
        loader.add_css("location", "div[data-testid='jobsearch-JobInfoHeader-companyLocation']::text", default=DEFAULT_VALUE)
        
        loader.add_css("job_type", "div#jobDetailsSection div[aria-label='İş türü'] span::text", default=DEFAULT_VALUE)
        
        loader.add_xpath('job_description', '//div[@id="jobDescriptionText"]//text()')

        loader.add_value("url", response.url)

        loader.add_value('source_site', 'indeed.com')

        yield loader.load_item()

