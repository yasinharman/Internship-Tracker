import scrapy
from scrapy_playwright.page import PageMethod
from scrapy.loader import ItemLoader
from random import *


class KariyernetSpider(scrapy.Spider):
    name = "kariyerNet"

    def start_requests(self):
        yield scrapy.Request(
            url = "https://www.kariyer.net/is-ilanlari/istanbul-bilisim?ct=34,82&cs=001000000&wa=22,78",
            meta={
                "playwright": True,
                
                "playwright_context_kwargs": {
                    "has_touch": False,
                    "is_mobile": False,
                    "device_scale_factor": 1.0,
                },

                "playwright_include_page": True,

                "playwright_page_methods": [

                    PageMethod("wait_for_load_state", "domcontentloaded"),

                    PageMethod("wait_for_selector", "div.list-items-wrapper"),

                    PageMethod(
                        "evaluate",
                        """async () => {
                            const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                            let previousHeight = 0;
                            let sameHeightCounter = 0;
                            const maxSameHeight = 3;
                            while (sameHeightCounter < maxSameHeight) {
                                window.scrollTo(0, document.body.scrollHeight);
                                await delay(1000);
                                const newHeight = document.body.scrollHeight;
                                if (newHeight === previousHeight) {
                                    sameHeightCounter += 1;
                                } else {
                                    sameHeightCounter = 0;
                                    previousHeight = newHeight;
                                }
                                }
                        }"""
                    )

                    # PageMethod("wait_for_timeout", randint(2000, 3000))

                ]            
                },
                callback=self.parse
        )

    def parse(self, response):
        all_links = []

        container = response.css("div.list-items-wrapper")
        links = container.css("div[data-test='ad-card'] a[data-test='ad-card-item']::attr(href)").getall()

        for link in links:
            all_links.append(link)

        for i in all_links:
            yield scrapy.Request(
                url = response.urljoin(i),
                meta={
                "playwright": True,
                
                "playwright_context_kwargs": {
                    "has_touch": False,
                    "is_mobile": False,
                    "device_scale_factor": 1.0,
                },

                # "playwright_include_page": True,

                "playwright_page_methods": [

                    PageMethod("wait_for_load_state", "domcontentloaded"),
                    PageMethod("wait_for_selector", "div.details-container"),
                    PageMethod("wait_for_timeout", randint(2000, 3000))
                ]
                }
            )
    
    def parse_detail(self, response):
        container = response.css("div.main-container")

        DEFAULT_VALUE = "N/A"

        try:
            job_title = container.css("div[data-test='job-title']::text").get(DEFAULT_VALUE)
            company = container.css("a[data-test='company-name']::text").get(DEFAULT_VALUE)
            location = container.css("span[data-test='company-location']::text").get(DEFAULT_VALUE)
            wfh = container.css("p.mb-0").get(DEFAULT_VALUE)
            work_method = container.css('p[data-test="detail-work-type"]::text').get(DEFAULT_VALUE)
            experience = container.css('p[data-test="detail-experience-level"]::text').get(DEFAULT_VALUE)
            department = container.css('p[data-test="detail-department-info"]::text').get(DEFAULT_VALUE)
            appoinment_number = container.css('div.detail:nth-child(4) p::text').get(DEFAULT_VALUE)
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")


        yield {
            "Job Title": job_title,
            "Company Name": company,
            "Location": location,
            "Work Place": wfh,
            "Work Method": work_method,
            "Experience": experience,
            "Department": department,
            "Appointment Number": appoinment_number,
        }

