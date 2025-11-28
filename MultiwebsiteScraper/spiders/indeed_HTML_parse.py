import scrapy  # Web kazıma çatısı.
from urllib.parse import urlencode  # URL parametrelerini (q=python&l=istanbul gibi) düzgün formatlamak için.

class IndeedJobSpider(scrapy.Spider):
    name = "indeed_html"

    custom_settings = {
        'SCRAPEOPS_API_KEY': ' ',
        'SCRAPEOPS_PROXY_ENABLED': True,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapeops_scrapy_proxy_sdk.scrapeops_scrapy_proxy_sdk.ScrapeOpsScrapyProxySdk': 725,
        },
        # Indeed için özel hız ayarları da ekleyebilirsin:
        'CONCURRENT_REQUESTS': 1, 
        'DOWNLOAD_DELAY': 1,
    }

    def get_indeed_search_url(self, keyword, location, offset=0):
        parameters = {"q": keyword, "l": location, "filter": 0, "start": offset}
        return "https://www.indeed.com/jobs?" + urlencode(parameters)
    
    def start_requests(self):
        keyword_list = ['python']
        location_list = ['istanbul']
        
        for keyword in keyword_list:
            for location in location_list:
                indeed_jobs_url = self.get_indeed_search_url(keyword, location)
                
                yield scrapy.Request(
                    url=indeed_jobs_url, 
                    callback=self.parse_job_links, 
                    meta={
                        'keyword': keyword,
                        'location': location,
                        'offset': 0
                          }
                )
    
    def parse_job_links(self, response):
        container = response.css("div#mosaic-provider-jobcards ul")
        all_jobs = container.css("div.job_seen_beacon")

        for job in all_jobs:
            link = job.css("h2.jobTitle a::attr(href)").get()

            yield scrapy.Request(
                url = response.urljoin(link),
                callback = self.parse_job_detail
            )

    def parse_job_detail(self, response):
        container = response.css("div.jobsearch-JobComponent")

        job_title = container.css("h1[data-testid='jobsearch-JobInfoHeader-title']::text").get()
        company = container.css("div[data-testid='inlineHeader-companyName'] a::text").get()
        location = container.css("div[data-testid='jobsearch-JobInfoHeader-companyLocation'] span::text").get()

        yield {
            'job_title': job_title,
            'company': company,
            'location': location
            }

