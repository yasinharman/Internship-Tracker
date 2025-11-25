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

class IndeedSpider(scrapy.Spider):
    name = "indeed"
        
    def start_requests(self):
        start_url = "https://tr.indeed.com/jobs?q=python&l=%C4%B1stanbul&from=searchOnDesktopSerp%2Cwhereautocomplete&cf-turnstile-response=0.9UvMZs1AdlXR99nnM3zCmujFj93lmr6qtWr9aXl9SCFOsgTkhYKY5vL6Mo-zMZvDdj_hYSyNAK1UDXDDgjJkpJ6tyIj08NWbpfJVum_m5fWjtw8AI7fr8rxqrIJHlBtN6On03FPo1wlWtgWPn6_QTEJtHT1-oUYMgfEv_7cGxHUPSVCaRmNXirKRlC1yrEjLOBbpYGE2pik441GqsTRloIaOmQQ8iCK98fyc7gqoq8Ma_ONTkyQ0UrZW7aErqMMtZTUY7kNUgqgW7W9rZqbOA1oHMsiG4QrY2f-0aeX7inqpiCllEUpspD7i9cnZORKoqpT0lNO_Ml8ozIRuIsYg4S_8dybnu8JR4ri0XI553Bo_dSdMYZqtyqFXzhkG_jI6kj61rOBFcZVNRXPOsavGn_UbDosszYgV7vP0UlfVCXWHnCf_NHuU0O1seTaAqccZ1uPSTD7fWiGronBLPlln8rOVdk9imw53AvBdjR-Vo3PuC7Xj09qU97OwVlUecEDQiimqkJpLVuKobGlvhV_pgvMk5Kc81eSkvKzgOeCgzx1kn3xSEt7cr4cQ1gzxKAkVVVZDn56erNM5UK2RqSH1f4DVMPMGUqoL2RQsRYzlNzWV3JVgK-qrSilBc6HrOOO6A6IQ64bZn0hCvBvjS8-tqkDTJIpZcQWPPP2JgbDKPkraZYRuvs77pcNr2ICBIaI_qg6HN0qT3BNvMqO9y82BwYGBzeAOgyrqpvf8c1tYfYHpWgHdtTwfiXGQEOa8OsScWyIGuYUU8bU8cFIIIhBAtWuXyeZxFxYyzI5DuSOb1oRIGPVRc5YM85D2DCxdPnUiMnXF-9PBgOW2PZW_439oy0sQrFOpj_87R29mlmAzLjoVUwA7X_k_GVzTjkYiJaf9142RkMRv0i4ZJH4LjkwEUw.lSGo3XIz1VFS7PBXkLlfWw.e42c98b57049e3b01589f9243b24a831e3f0a5365a5908a4deaa383821187dfd&vjk=7cfa99b0592955b2"

        yield scrapy.Request(
            url = start_url,
            meta = meta_for_first_tabs(),
            callback = self.parse
        )
    
    def parse():
        ...
