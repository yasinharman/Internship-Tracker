import scrapy
from scrapy_playwright.page import PageMethod
from scrapy.loader import ItemLoader
from MultiwebsiteScraper.items import KariyerNetItem # ITEM AYARLAMASI YAPILACAK
from random import randint

class KariyernetSpider(scrapy.Spider):
    name = "kariyerNet"

    def start_requests(self):
        start_url = "https://www.kariyer.net/is-ilanlari/istanbul-bilisim?ct=34,82&cs=001000000&wa=22,78"

        yield scrapy.Request(
            url = start_url,
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
                            """
                        async () => {
                            const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                            const randomInt = (min, max) =>
                                Math.floor(Math.random() * (max - min + 1)) + min;

                            let previousHeight = 0;
                            let sameHeightCounter = 0;
                            const maxSameHeight = 3;

                            while (sameHeightCounter < maxSameHeight) {
                                const currentY = window.scrollY;
                                const maxY = Math.max(0, document.body.scrollHeight - window.innerHeight);
                                const distanceToBottom = maxY - currentY;

                                let targetY = currentY;

                                if (distanceToBottom < 400) {
                                    // Alta çok yaklaştıysan: biraz etrafta takıl, hafif yukarı/aşağı
                                    if (Math.random() < 0.5) {
                                        // Küçük yukarı scroll
                                        targetY = Math.max(0, currentY - randomInt(100, 400));
                                    } else {
                                        // Alta yakın küçük aşağı / yerinde gezinme
                                        targetY = Math.min(maxY, currentY + randomInt(50, 200));
                                    }
                                } else {
                                    // Normal durumda aşağı doğru daha büyük rastgele adım
                                    targetY = Math.min(maxY, currentY + randomInt(300, 800));
                                }

                                window.scrollTo({
                                    top: targetY,
                                    behavior: "smooth",
                                });

                                // Ortalama ~1 sn bekleme (800–1200 ms arası)
                                await delay(randomInt(800, 1200));

                                const newHeight = document.body.scrollHeight;

                                if (newHeight === previousHeight) {
                                    sameHeightCounter += 1;
                                } else {
                                    sameHeightCounter = 0;
                                    previousHeight = newHeight;
                                }
                            }
                        }
                        """
                    ),

                    # PageMethod("wait_for_timeout", randint(2000, 3000))

                ]            
                },
                callback=self.parse_all_links
        )


    def get_all_links(self, response):
        container = response.css("div.list-items-wrapper")
        links = container.css("div[data-test='ad-card'] a[data-test='ad-card-item']::attr(href)").getall()

        return links

    def parse_all_links(self, response):
        links = self.get_all_links(response)
        
        for link in links:
            yield scrapy.Request(
                url = response.urljoin(link), 
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

                    PageMethod("wait_for_selector", "div.main-container"),

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
                    
                    PageMethod("wait_for_timeout", randint(2000, 3000))
                ]            
                },
                callback=self.parse_detail
            )

        next_page_url = response.css("a[aria-label='Go to next page']::attr(href)").get()
        
        if next_page_url:
            yield scrapy.Request(
                url = response.urljoin(next_page_url),
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
                                """
                            async () => {
                                const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                                const randomInt = (min, max) =>
                                    Math.floor(Math.random() * (max - min + 1)) + min;

                                let previousHeight = 0;
                                let sameHeightCounter = 0;
                                const maxSameHeight = 3;

                                while (sameHeightCounter < maxSameHeight) {
                                    const currentY = window.scrollY;
                                    const maxY = Math.max(0, document.body.scrollHeight - window.innerHeight);
                                    const distanceToBottom = maxY - currentY;

                                    let targetY = currentY;

                                    if (distanceToBottom < 400) {
                                        // Alta çok yaklaştıysan: biraz etrafta takıl, hafif yukarı/aşağı
                                        if (Math.random() < 0.5) {
                                            // Küçük yukarı scroll
                                            targetY = Math.max(0, currentY - randomInt(100, 400));
                                        } else {
                                            // Alta yakın küçük aşağı / yerinde gezinme
                                            targetY = Math.min(maxY, currentY + randomInt(50, 200));
                                        }
                                    } else {
                                        // Normal durumda aşağı doğru daha büyük rastgele adım
                                        targetY = Math.min(maxY, currentY + randomInt(300, 800));
                                    }

                                    window.scrollTo({
                                        top: targetY,
                                        behavior: "smooth",
                                    });

                                    // Ortalama ~1 sn bekleme (800–1200 ms arası)
                                    await delay(randomInt(800, 1200));

                                    const newHeight = document.body.scrollHeight;

                                    if (newHeight === previousHeight) {
                                        sameHeightCounter += 1;
                                    } else {
                                        sameHeightCounter = 0;
                                        previousHeight = newHeight;
                                    }
                                }
                            }
                            """
                        ),

                        # PageMethod("wait_for_timeout", randint(2000, 3000))

                    ]            
                    },
                    callback=self.parse_all_links
            )
    
    def parse_detail(self, response):
        container = response.css("div.main-container")

        DEFAULT_VALUE = "N/A"
        loader = ItemLoader(item=KariyerNetItem(), selector=container)

        loader.add_css("job_title", "div[data-test='job-title']::text", default=DEFAULT_VALUE)
        loader.add_css("company", "a[data-test='company-name']::text", default=DEFAULT_VALUE)
        loader.add_css("location", "span[data-test='company-location']::text", default=DEFAULT_VALUE)
        loader.add_css("work_method", 'p[data-test="detail-work-type"]::text', default=DEFAULT_VALUE)
        loader.add_css("experience", 'p[data-test="detail-experience-level"]::text', default=DEFAULT_VALUE)
        loader.add_css("department", 'p[data-test="detail-department-info"]::text', default=DEFAULT_VALUE)
        loader.add_css("appointment_count", 'div.detail:nth-child(4) p::text', default=DEFAULT_VALUE)

        yield loader.load_item()

