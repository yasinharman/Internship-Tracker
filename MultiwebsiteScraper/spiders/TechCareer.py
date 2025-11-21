import scrapy
from scrapy_playwright.page import PageMethod
from scrapy.loader import ItemLoader
from MultiwebsiteScraper.items import KariyerNetItem # ITEM AYARLAMASI YAPILACAK
from random import randint
from pathlib import Path

def meta_for_first_tabs():
    return {
            "playwright": True,
            
            "playwright_context": "kariyer_proxy_context",

            "playwright_include_page": True,

            "playwright_page_methods": [

                PageMethod("wait_for_load_state", "domcontentloaded"),

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
        }


def meta_for_back_to_back_pages(): 
    return {
            "playwright": True,
            
            "playwright_context": "kariyer_proxy_context",

            # "playwright_include_page": True,

        }


class TechcareerSpider(scrapy.Spider):
    name = "TechCareer"
    
    def start_requests(self, response):
        start_url = "https://www.techcareer.net/jobs/detail/bilgi-islem-uzman-4302273"

        yield scrapy.Request(
            url=start_url,
            meta=meta_for_first_tabs(),
            callback=self.parse
        )
    
    def parse(self, response):
        ...