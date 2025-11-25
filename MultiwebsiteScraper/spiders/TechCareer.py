import scrapy
from scrapy_playwright.page import PageMethod
from scrapy.loader import ItemLoader
from MultiwebsiteScraper.items import TechCareerItem # ITEM AYARLAMASI YAPILACAK
from random import randint
from pathlib import Path

def meta_for_first_tabs(context_id=None):
    meta = {
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
    if context_id:
        # Context ID varsa meta'ya ekle
        meta["playwright_context_id"] = context_id 
        
    return meta

def meta_for_back_to_back_pages(context_id=None): 
    meta = {
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
    if context_id:
        # Context ID varsa meta'ya ekle
        meta["playwright_context_id"] = context_id 
        
    return meta

class TechcareerSpider(scrapy.Spider):
    name = "TechCareer"

    def start_requests(self):
        PLAYWRIGHT_CONTEXT_ID = "persisted_context"

        for i in range(1, 4):
            start_url = f"https://www.techcareer.net/jobs?jobs[search][select]=position&jobs[search][location]=%C4%B0stanbul%28Avr.%29%20%2F%20T%C3%BCrkiye&jobs[isCompleted]=false&jobs[page]={i}"

            yield scrapy.Request(
                url = start_url,
                meta = meta_for_first_tabs(context_id=PLAYWRIGHT_CONTEXT_ID),
                callback = self.parse_all_links,
            )
    
    async def parse_all_links(self, response):
        # Oluşturulan context_id'yi response.meta'dan alıp takip eden isteklere aktarıyoruz.
        current_context_id = response.meta.get("playwright_context_id")
        
        # Sayfa nesnesini alıyoruz (çünkü include_page=True dedik)
        page = response.meta["playwright_page"]

        try:
            main_container = response.css("div[data-test='jobs-list']")
            all_jobs = main_container.css("a[data-test='single-job-item']::attr(href)").getall()
            
            for job in all_jobs:
                yield scrapy.Request(
                    url = response.urljoin(job),
                    # Detay sayfaları için aynı context ID'yi kullanarak tarayıcının yeniden açılmasını önlüyoruz.
                    meta = meta_for_back_to_back_pages(context_id=current_context_id),
                    callback = self.parse_detail
                )
        finally:
            # KRİTİK NOKTA: İşimiz bitince listeleme sayfasını kapatıyoruz.
            # Bu yapılmazsa persistent context içinde sekmeler birikir ve bot tıkanır.
            await page.close()


    def parse_detail(self, response):

        container = response.css("div.css-suqyto")
        
        DEFAULT_VALUE = "N/A"
        loader = ItemLoader(item=TechCareerItem(), selector=container)

        loader.add_css("job_title", "h1[data-test='job-detail-title']::text", default=DEFAULT_VALUE)
        loader.add_css("company", "h2[data-test='job-detail-company-name']::text", default=DEFAULT_VALUE)
        loader.add_css("location", "h3.css-1ywrvz7::text", default=DEFAULT_VALUE)
        loader.add_css("work_method", "h3.css-hpmb9t strong::text", default=DEFAULT_VALUE)
        loader.add_css("experience", "h3.css-1ywrvz7::text", default=DEFAULT_VALUE)

        yield loader.load_item()






