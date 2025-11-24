import scrapy
from scrapy_playwright.page import PageMethod
from scrapy.loader import ItemLoader
from MultiwebsiteScraper.items import KariyerNetItem # ITEM AYARLAMASI YAPILACAK
from random import randint
from pathlib import Path

def meta_for_first_tabs():
    return {
            "playwright": True,
            
            "playwright_context_kwargs": {
                "is_mobile": False,
                "has_touch": False,
                "device_scale_factor": 1.25,
                "viewport": {"width": 1536, "height": 864},
                "locale": "tr-TR",
                "timezone_id": "Europe/Istanbul"

            },

            "playwright_include_page": True,

            "playwright_page_methods": [

                PageMethod("wait_for_load_state", "domcontentloaded"),
                
                PageMethod("wait_for_selector", "div.customScrollBar"),

                PageMethod(
                        "evaluate",
                        """
                            async () => {
                            const selector = ".customScrollBar";
                            const delay = (ms) => new Promise(res => setTimeout(res, ms));
                            const rand = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;

                            const container = document.querySelector(selector);
                            if (!container) return; // Element yoksa hemen çık

                            let totalHeight = 0;
                            let distance = 300; // Her seferinde kaydırılacak piksel
                            let stable_counter = 0; // Değişiklik olmama sayacı
                            let total_loops = 0; // Toplam döngü sayacı (SONSUZ DÖNGÜ ENGELLEYİCİ)
                            
                            // AYARLAR
                            const max_stable_checks = 5; // Yükseklik 5 kere değişmezse dur.
                            const max_loops = 100; // Ne olursa olsun 100 kaydırmadan sonra dur (Emniyet sübabı).

                            while (total_loops < max_loops) {
                                const scrollHeight = container.scrollHeight;
                                const currentScroll = container.scrollTop + container.clientHeight;

                                // En alta kadar kaydır
                                container.scrollBy({ top: distance, behavior: 'smooth' });
                                
                                // Rastgele bekle (İnsansı davranış ve yükleme süresi)
                                await delay(rand(400, 800));

                                // Yeni yüksekliği kontrol et
                                const newScrollHeight = container.scrollHeight;

                                if (newScrollHeight === scrollHeight && currentScroll >= newScrollHeight - 50) {
                                    // Eğer yükseklik değişmediyse VE zaten en alttaysak
                                    stable_counter++;
                                } else {
                                    // Yükseklik arttıysa veya daha yolumuz varsa sayacı sıfırla
                                    stable_counter = 0;
                                }

                                // Eğer X defadır yükseklik değişmiyorsa, sonuna gelmişizdir.
                                if (stable_counter >= max_stable_checks) {
                                    console.log("Sayfa sonuna ulaşıldı (Stable count limit).");
                                    break; 
                                }

                                total_loops++;
                            }
                            
                            if (total_loops >= max_loops) {
                                console.log("Maksimum döngü sınırına takıldı, işlem zorla bitiriliyor.");
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

            "playwright_context_kwargs": {
                "is_mobile": False,
                "has_touch": False,
                "device_scale_factor": 1.25,
                "viewport": {"width": 1536, "height": 864},
                "locale": "tr-TR",
                "timezone_id": "Europe/Istanbul"
            },

            "playwright_page_methods": [

                PageMethod("wait_for_load_state", "domcontentloaded"),

                PageMethod("wait_for_selector", "div.css-suqyto"),
                
                PageMethod("wait_for_timeout", randint(1500, 2500))
            ]
        }

class TechcareerSpider(scrapy.Spider):
    name = "TechCareer"
    
    def __init__(self):
        all_job_links = []
        self.all_job_links = all_job_links

    def start_requests(self):
        start_url = "https://www.techcareer.net/jobs?jobs[search][select]=position&jobs[search][location]=%C4%B0stanbul%28Avr.%29%20%2F%20T%C3%BCrkiye&jobs[isCompleted]=false&jobs[page]=1"

        yield scrapy.Request(
            url = start_url,
            meta = meta_for_first_tabs(),
            callback = self.parse_all_links,
        )
    
    def parse_all_links(self, response):

        main_container = response.css("div[data-test='jobs-list']")
        all_jobs = main_container.css("a[data-test='single-job-item']::attr(href)").getall()

        self.all_job_links.extend(all_jobs)
        
        next_page_check = response.css("a[aria-disabled='true'][aria-label='Go to next page']")
        
        if not next_page_check:
            next_page_url = response.css("a[aria-label='Go to next page']::attr(href)").get()

            yield scrapy.Request(
                url = response.urljoin(next_page_url),
                meta = meta_for_first_tabs(),
                callback = self.parse_all_links
            )
        else:
            for job in self.all_job_links:
                yield scrapy.Request(
                    url = response.urljoin(job),
                    meta = meta_for_back_to_back_pages(),
                    callback = self.parse_detail
                )

    def parse_detail(self, response):

        container = response.css("div.css-suqyto")

        job_title = container.css("h1[data-test='job-detail-title']::text").get()
        company = container.css("h2[data-test='job-detail-company-name']::text").get()
        location = container.css("h3.css-1ywrvz7::text").get()
        work_method = container.css("h3.css-hpmb9t strong::text").get()
        experience = container.css("h3.css-1ywrvz7::text").get()

        yield{
            "job_title": job_title,
            "company": company,
            "location": location,
            "work_method": work_method,
            "experience": experience
        }






