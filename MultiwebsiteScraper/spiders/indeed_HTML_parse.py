import scrapy
from urllib.parse import urlencode

class IndeedJobSpider(scrapy.Spider):
    name = "indeed_html"

    custom_settings = {
        # LÜTFEN API KEY'İNİ AŞAĞIYA YAPIŞTIR
        'SCRAPEOPS_API_KEY': '', 
        'SCRAPEOPS_PROXY_ENABLED': True,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapeops_scrapy_proxy_sdk.scrapeops_scrapy_proxy_sdk.ScrapeOpsScrapyProxySdk': 725,
        },
        'CONCURRENT_REQUESTS': 1, 
        'DOWNLOAD_DELAY': 2,
        
        'DEFAULT_REQUEST_HEADERS': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Referer': 'https://tr.indeed.com/',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'same-origin',
                    'Sec-Fetch-User': '?1',
                },
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
                            'sops_render_js': True, #####
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
                        # 'sops_render_js': True,
                        'keyword': response.meta.get('keyword') # Keyword verisini taşımaya devam et
                    }
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

