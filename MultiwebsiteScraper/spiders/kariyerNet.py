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
                    ),

                    PageMethod("screenshot", path="example.png", full_page=True)

                    # PageMethod("wait_for_timeout", randint(2000, 3000))

                ]            
                },
                callback=self.parse
        )

    def parse(self, response):
        ...
        
