import scrapy
from scrapy_playwright.page import PageMethod
from ..loaders import TechCareerLoader
from random import randint

'''
    In this website antibot protection is not heavy 
    so we are using playwright for the bypass protocol
'''

def meta_for_first_tabs(context_id=None):

    ############################################################
    # PLAYWRIGHT ACTIVATION AND PAGE METHODS FOR THE FIRST TAB #
    ############################################################
    
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

            ]
        }
    if context_id:
        # WE ARE RETURNING CONTEXT ID WITH META TO USE SAME CONTEXT ON EVERY REQUEST #
        meta["playwright_context_id"] = context_id 
        
    return meta

def meta_for_back_to_back_pages(context_id=None):

    #######################################################################
    # PLAYWRIGHT ACTIVATION AND PAGE METHODS FOR THE JOB APPLICATION TABS #
    #######################################################################

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
        # WE ARE RETURNING CONTEXT ID WITH META TO USE SAME CONTEXT ON EVERY REQUEST #
        meta["playwright_context_id"] = context_id 
        
    return meta

class TechcareerSpider(scrapy.Spider):
    name = "TechCareer"

    
    ####################################################
    # CUSTOM SETTINGS THAT ONLY ENABLED ON THIS SPIDER #
    ####################################################

    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },

        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",

        "PLAYWRIGHT_LAUNCH_OPTIONS": {
            "headless": False, # Hata ayıklarken False yapın, görebilmek için
            "args": [
                "--disable-blink-features=AutomationControlled", # Bot olduğunuzu gizler
                "--no-sandbox",
            ]
        },
        # WE ARE ADDING A TIMEOUT TO LOAD JAVASCRIPT BEFORE PARSING THE HTML WHEN WE OPEN THE FIRST TAB # 
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30000,
    }


    ##########################################
    # SENDING THE REQUEST TO THE WEBSITE URL #
    ##########################################

    def start_requests(self):
        PLAYWRIGHT_CONTEXT_ID = "persisted_context"

        for i in range(1, 4):
            start_url = f"https://www.techcareer.net/jobs?jobs[isCompleted]=false&jobs[page]={i}"

            yield scrapy.Request(
                url = start_url,
                meta = meta_for_first_tabs(context_id=PLAYWRIGHT_CONTEXT_ID),
                callback = self.parse_all_links,
            )
    
    async def parse_all_links(self, response):
        # TAKING THE CONTEXT ID FROM THE META TO USE ON ALL REQUESTS #
        current_context_id = response.meta.get("playwright_context_id")
        
        # GETTING THE PAGE OBJECT FROM THE META #
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
            # WE ARE CLOSING THE PAGE TO RESTART PERSISTENT CONTEXT #
            await page.close()


    ######################################################
    # PARSING THE DETAILS FROM THE JOB APPLICATION PAGES #
    ######################################################

    def parse_detail(self, response):
        
        DEFAULT_VALUE = "N/A"
        loader = TechCareerLoader(response=response)

        
        loader.add_css("job_title", "h1[data-test='job-detail-title']::text", default=DEFAULT_VALUE)
        
        loader.add_css("company", "h2[data-test='job-detail-company-name']::text", default=DEFAULT_VALUE)
        loader.add_css("company", "h2[data-test='job-detail-company-name'] a::text", default=DEFAULT_VALUE)
        
        loader.add_css("location", "div[data-test='job-detail-location'] h3.css-1ywrvz7::text", default=DEFAULT_VALUE)
        
        loader.add_css("job_type", "h3.css-hpmb9t strong::text", default=DEFAULT_VALUE)
        
        loader.add_css('job_description', 'div[data-test="job-detail-desc-content"] *::text')

        loader.add_value("url", response.url)

        loader.add_value("source_site", "techcareer.com")

        yield loader.load_item()






