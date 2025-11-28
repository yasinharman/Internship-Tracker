import scrapy
from urllib.parse import urlencode

class IndeedJobSpider(scrapy.Spider):
    name = "indeed_html"

    custom_settings = {
        # LÜTFEN API KEY'İNİ AŞAĞIYA YAPIŞTIR
        'SCRAPEOPS_API_KEY': 'BURAYA_API_KEY_YAZMAYI_UNUTMA', 
        'SCRAPEOPS_PROXY_ENABLED': True,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapeops_scrapy_proxy_sdk.scrapeops_scrapy_proxy_sdk.ScrapeOpsScrapyProxySdk': 725,
        },
        'CONCURRENT_REQUESTS': 1, 
        'DOWNLOAD_DELAY': 2,
    }

    def get_indeed_search_url(self, keyword, location, offset=0):
        parameters = {"q": keyword, "l": location, "filter": 0, "start": offset}
        return "https://www.indeed.com/jobs?" + urlencode(parameters)
    
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
                            'page_num': page + 1
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
                    callback = self.parse_job_detail
                )

    def parse_job_detail(self, response):
        container = response.css("div.jobsearch-JobComponent")

        job_title = container.css("h1[data-testid='jobsearch-JobInfoHeader-title']::text").get()
        
        company = container.css("div[data-testid='inlineHeader-companyName'] a::text").get()
        if not company:
            company = container.css("div[data-testid='inlineHeader-companyName']::text").get()
            
        location = container.css("div[data-testid='jobsearch-JobInfoHeader-companyLocation'] span::text").get()
        if not location:
             location = container.css("div[data-testid='jobsearch-JobInfoHeader-companyLocation']::text").get()

        yield {
            'keyword': response.meta.get('keyword'),
            'job_title': job_title,
            'company': company,
            'location': location,
            'url': response.url
        }

