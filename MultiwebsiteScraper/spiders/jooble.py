import scrapy
import json
from ..loaders import JoobleLoader

###############
# MAIN SPIDER #
###############

class JoobleUrlCrawler(scrapy.Spider):
    name = "jooble"
    api_url = "https://tr.jooble.org/api/serp/jobs"


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
                    'Accept': 'application/json',
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

    ############################################
    # SENDING THE FIRST REQUEST TO THE WEBSITE #
    ############################################

    def start_requests(self):

        '''
        In this website the api type is post api 
        so we will need to use websites api payload 
        to be able to do pagination
        '''

        payload = {
            "page": 1,
            "region": "İstanbul",
            "search": "python",
            "regionId": 56560
        }

        yield scrapy.Request(
            url=self.api_url,
            method='POST', # THIS SETTING IS IMPORTANT !!!!!!
            body=json.dumps(payload),# THIS SETTING IS IMPORTANT !!!!!!
            headers={
                "Content-Type": "application/json", # THIS SETTING IS IMPORTANT !!!!!!
            },
            callback=self.parse,
            meta={'page_num': 1}
        )


    ########################################################
    # PARSING THE JOB APPLICATIONS URLS FROM THE JSON TEXT #
    ########################################################

    def parse(self, response):
            
            # PARSING THE URL FROM JSON #
            ##########################################
            try:
                data = json.loads(response.text)
            except json.JSONDecodeError:
                self.logger.error("JSON could'nt parse")
                return

            jobs = data.get('jobs', [])
            
            if not jobs:
                self.logger.info("No more job applications.")
                return 

            for job in jobs:
                job_url = job.get('url')
                if job_url:
                    yield {'url': job_url}
            ##########################################
            
            # PAGINATION #
            ##########################################
            current_page = response.meta['page_num']
            
            next_page = current_page + 1

            if next_page > 20:
                return
            
            new_payload = {
                "page": next_page,
                "region": "İstanbul",
                "search": "python",
                "regionId": 56560
            }
            ###########################################

            yield scrapy.Request(
                url=self.api_url,
                method='POST',
                body=json.dumps(new_payload), # new_payload'u json string'e çevir
                headers={"Content-Type": "application/json"},
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
        'SCRAPEOPS_API_KEY': '', 
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

