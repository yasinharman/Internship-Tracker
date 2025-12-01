import scrapy
from urllib.parse import urlencode

class IndeedJobSpider(scrapy.Spider):
    name = "indeed_html"

    custom_settings = {
        'SCRAPEOPS_API_KEY': '9978eae2-0811-40b7-908d-28c38d5f4e3b', 
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
                        'sops_residential': False,
                        'sops_country': 'tr',
                    }
                )

    def parse_job_detail(self, response):
        container = response.css("div.jobsearch-JobComponent")

        
        job_title = container.css("h1[data-testid='jobsearch-JobInfoHeader-title'] span::text").get()
        
        company = container.css("div[data-testid='inlineHeader-companyName'] a::text").get()
        if not company:
            company = container.css("div[data-testid='inlineHeader-companyName']::text").get()
        
        location = container.css("div[data-testid='jobsearch-JobInfoHeader-companyLocation'] span::text").get()
        if not location:
             location = container.css("div[data-testid='jobsearch-JobInfoHeader-companyLocation']::text").get()
        
        text_nodes = response.xpath('//div[@id="jobDescriptionText"]//text()').getall()
        job_description = " ".join([text.strip() for text in text_nodes if text.strip()])

        source_site = "linkedin"





        yield {
            'job_title': job_title,
            'company': company,
            'location': location,
            "job_description": job_description,
            'url': response.url,
            "source_site": source_site,

        }

