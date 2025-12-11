import scrapy
from urllib.parse import urlencode
from ..loaders import KariyerNetLoader

class KariyernetSpider(scrapy.Spider):
    name = "kariyerNet"


    ####################################################
    # CUSTOM SETTINGS THAT ONLY ENABLED ON THIS SPIDER #
    ####################################################

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
    
    ##############################################
    # DEBUG AND CACHE SETTINGS FOR THE TEST RUNS #
    ##############################################

    # ENABLES THE CACHE #
    'HTTPCACHE_ENABLED' : True,

    # CACHE TIME (Seconds) #
    # '0' MEANS IT WILL BE STORED FOREVER #
    'HTTPCACHE_EXPIRATION_SECS' : 0,

    # NAME OF THE STORAGE FILE FOR THE CACHE FILES #
    'HTTPCACHE_DIR' : 'httpcache_indeed',

    # WE ARE ONLY TAKING THE RESULTS OF THE SUCCESFUL REQUESTS #
    'HTTPCACHE_IGNORE_HTTP_CODES' : [400, 401, 403, 404, 429, 500, 503],

    # USE DEFAULT FILE SYSTEM STORAGE #
    'HTTPCACHE_STORAGE' : 'scrapy.extensions.httpcache.FilesystemCacheStorage'

    }


    ###########################################
    # CREATING A SEARCH URL TO SEND A REQUEST #
    ###########################################
    
    def get_kariyer_search_url(self, city_plate_number, keyword, page_num):
        parameters = {"ct": city_plate_number, "kw": keyword, "cp":page_num}
        return "https://www.kariyer.net/is-ilanlari?" + urlencode(parameters)


    ##################################################
    # SENDING THE REQUEST TO THE URL THAT WE CREATED #
    ################################################## 

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
                            'sops_render_js': True, # ENABLING THE JS RENDER OPTION FROM THE SOPS SERVICE 
                            'sops_country': 'tr' # kariyer.net is a turkish website so we are using the turkish proxies
                        }
                    )
    

    ########################################################
    # PARSING THE JOB APPLICATION URLS FROM THE FIRST PAGE #
    ########################################################

    def parse_job_links(self, response):
        container = response.css("div.list-items-wrapper")
        job_links = container.css("div[data-test='list-items']")

        for job_link in job_links:
            link = job_link.css("div[data-test='ad-card'] a[data-test='ad-card-item']::attr(href)").get()
            yield scrapy.Request(
                url = response.urljoin(link),
                callback=self.parse_detail,
                meta={
                    'sops_render_js': False, # WE ARE DISABLING THE JS RENDER OPTION FROM THE SOPS SERVICE TO SAVE API CREDIT
                    'sops_country': 'tr',
                }
            )


    #########################################################
    # PARSING THE JOB DETAILS FROM THE JOB APPLICATION URLS #
    #########################################################

    def parse_detail(self, response):

        DEFAULT_VALUE = "N/A"
        loader = KariyerNetLoader(response=response)

        loader.add_css("job_title", "div[data-test='job-title']::text", default=DEFAULT_VALUE)
        
        loader.add_css("company", "a[data-test='company-name']::text", default=DEFAULT_VALUE)
        
        loader.add_css("location", "span[data-test='company-location']::text", default=DEFAULT_VALUE)
        
        loader.add_css("job_type", '.job-feature-list span:nth-child(2)::text', default=DEFAULT_VALUE)
        
        loader.add_xpath('job_description', '//div[@data-test="qualifications-and-job-description"]//text()')
        
        loader.add_value("url", response.url)
        
        loader.add_value("source_site", 'kariyernet.com')

        yield loader.load_item()

