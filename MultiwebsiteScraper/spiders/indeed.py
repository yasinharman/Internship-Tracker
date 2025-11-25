import scrapy
from scrapy_playwright.page import PageMethod
from scrapy.loader import ItemLoader
from MultiwebsiteScraper.items import TechCareerItem # ITEM AYARLAMASI YAPILACAK
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
                "timezone_id": "Europe/Istanbul",

                "ignore_https_errors": True,
                "args": [
                    "--disable-blink-features=AutomationControlled", # En kritik flag
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-position=0,0",
                    "--ignore-certifcate-errors",
                    "--ignore-certifcate-errors-spki-list",
                    # Gerçek bir Chrome gibi görünmesini sağlar
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36" 
                ]

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

class IndeedSpider(scrapy.Spider):
    name = "indeed"
        
    def start_requests(self):
        start_url = "https://tr.indeed.com/jobs?q=python&l=%C4%B1stanbul"

        yield scrapy.Request(
            url = start_url,
            meta = meta_for_first_tabs(),
            callback = self.parse
        )
    
    def parse():
        ...
