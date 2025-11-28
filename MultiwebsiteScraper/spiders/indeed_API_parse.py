import re  # Regular Expression: Metin içinde desen aramak (JS kodu içinden veri çekmek) için.
import json  # Çekilen metin tabanlı veriyi Python sözlüğüne (dictionary) çevirmek için.
import scrapy  # Web kazıma çatısı.
from urllib.parse import urlencode  # URL parametrelerini (q=python&l=istanbul gibi) düzgün formatlamak için.

class IndeedJobSpider(scrapy.Spider):
    name = "indeed_json"  # Terminalden 'scrapy crawl indeed' diyerek çalıştırmak için örümcek ismi.

    # 1. Yardımcı Fonksiyon: URL Oluşturucu
    # Neden? Kod tekrarını önlemek ve URL parametrelerini temiz bir şekilde yönetmek için.
    def get_indeed_search_url(self, keyword, location, offset=0):
        # Parametreleri sözlük olarak tanımlıyoruz. 
        # offset (start): Sayfalama için kullanılır (0, 10, 20...). Indeed her sayfada 10-15 ilan gösterir.
        parameters = {"q": keyword, "l": location, "filter": 0, "start": offset}
        # urlencode bu sözlüğü 'q=keyword&l=location...' formatına çevirir ve ana URL'e ekler.
        return "https://www.indeed.com/jobs?" + urlencode(parameters)

    # 2. Başlangıç Noktası (Entry Point)
    # Scrapy çalıştırıldığında ilk buraya bakar.
    def start_requests(self):
        keyword_list = ['python']  # Aranacak kelimeler
        location_list = ['istanbul']  # Aranacak konumlar
        
        # Her kelime ve her lokasyon kombinasyonu için döngü kuruyoruz.
        for keyword in keyword_list:
            for location in location_list:
                # İlk sayfa (offset=0) için URL oluşturuyoruz.
                indeed_jobs_url = self.get_indeed_search_url(keyword, location)
                
                # Scrapy'ye "Bu URL'e git ve dönen cevabı 'parse_search_results' fonksiyonuna yolla" diyoruz.
                # meta={...}: Parametreleri (keyword, location) bir sonraki fonksiyona taşımak için kullanılır.
                yield scrapy.Request(
                    url=indeed_jobs_url, 
                    callback=self.parse_search_results, 
                    meta={'keyword': keyword, 'location': location, 'offset': 0}
                )

    # 3. Arama Sonuçlarını İşleme (Liste Sayfası)
    def parse_search_results(self, response):
        # meta ile taşıdığımız verileri geri alıyoruz.
        location = response.meta['location']
        keyword = response.meta['keyword'] 
        offset = response.meta['offset'] 
        
        # --- KRİTİK BÖLÜM: HTML yerine Script Verisi Okuma ---
        # Indeed, ilan verilerini doğrudan HTML elementleri (div, span) içine koymak yerine,
        # sayfanın altındaki bir <script> etiketinin içine JSON olarak gömer.
        # Regex ile 'window.mosaic.providerData["mosaic-provider-jobcards"]=...' desenini arıyoruz.
        script_tag  = re.findall(r'window.mosaic.providerData\["mosaic-provider-jobcards"\]=(\{.+?\});', response.text)
        
        if script_tag is not None:
            # Regex ile bulduğumuz metni (string) gerçek bir Python sözlüğüne (dictionary) çeviriyoruz.
            json_blob = json.loads(script_tag[0])
        
            # --- Sayfalama (Pagination) Mantığı ---
            # Sadece ilk sayfadaysak (offset == 0) toplam sayfa sayısını hesaplarız.
            # Aksi takdirde her sayfada tekrar tekrar hesaplama yaparız.
            if offset == 0:
                # JSON içindeki meta veriden toplam ilan sayısını buluyoruz.
                meta_data = json_blob["metaData"]["mosaicProviderJobCardsModel"]["tierSummaries"]
                num_results = sum(category["jobCount"] for category in meta_data)
                
                # Güvenlik önlemi: Eğer 1000'den fazla ilan varsa, sadece ilk 50'sini çek (Test amaçlı sınırlandırma olabilir).
                # Gerçek kullanımda bu sınırı kaldırmak isteyebilirsiniz.
                if num_results > 1000:
                    num_results = 50
                
                # range(10, num_results, 10) -> 10, 20, 30... şeklinde artarak diğer sayfaların URL'lerini üretir.
                for offset in range(10, num_results + 10, 10):
                    url = self.get_indeed_search_url(keyword, location, offset)
                    # Diğer sayfalar için istek gönderiyoruz, yine aynı fonksiyona (kendisine) dönecek.
                    yield scrapy.Request(
                        url=url, 
                        callback=self.parse_search_results, 
                        meta={'keyword': keyword, 'location': location, 'offset': offset}
                    )

            # --- İlanları Listeden Çekme ---
            # JSON içindeki 'results' listesi o sayfadaki ilanları tutar.
            jobs_list = json_blob['metaData']['mosaicProviderJobCardsModel']['results']
            
            for index, job in enumerate(jobs_list):
                # 'jobkey': Indeed'in her ilan için verdiği benzersiz ID.
                if job.get('jobkey') is not None:
                    # Mobil/Basecamp görünümü genellikle daha temiz HTML/JSON verir, o yüzden bu URL yapısı tercih edilmiş.
                    job_url = 'https://www.indeed.com/m/basecamp/viewjob?viewtype=embedded&jk=' + job.get('jobkey')
                    
                    # Detay sayfasına gitmek için istek oluşturuyoruz.
                    # Bu sefer 'parse_job' fonksiyonunu çağırıyoruz çünkü artık liste değil, detay sayfasındayız.
                    yield scrapy.Request(url=job_url, 
                            callback=self.parse_job, 
                            meta={
                                'keyword': keyword, 
                                'location': location, 
                                'page': round(offset / 10) + 1 if offset > 0 else 1, # Sayfa numarasını hesaplama
                                'position': index,
                                'jobKey': job.get('jobkey'),
                            })
    
    # 4. İlan Detayını İşleme (Tekil İlan Sayfası)
    def parse_job(self, response):
        # Taşınan verileri al
        location = response.meta['location']
        keyword = response.meta['keyword']
        page = response.meta['page']
        position = response.meta['position']
        
        # Yine aynı mantık: İlanın tam açıklaması ve detayları '_initialData' adlı bir JS değişkeninde saklı.
        script_tag = re.findall(r"_initialData=(\{.+?\});", response.text)
        
        if script_tag:
            json_blob = json.loads(script_tag[0])
            # JSON ağacında gezinerek verileri çekiyoruz.
            job = json_blob["jobInfoWrapperModel"]["jobInfoModel"]['jobInfoHeaderModel']
            
            # Sanitized description: HTML etiketlerinden (kısmen) arındırılmış temiz metin.
            sanitizedJobDescription = json_blob["jobInfoWrapperModel"]["jobInfoModel"]['sanitizedJobDescription']
            
            # Scrapy'nin sonucu olarak veriyi dışarı aktarıyoruz (CSV veya JSON olarak kaydedilecek kısım).
            yield {
                'keyword': keyword,
                'location': location,
                'page': page,
                'position': position,
                'company': job.get('companyName'),
                'jobkey': response.meta['jobKey'],
                'jobTitle': job.get('jobTitle'),
                'jobDescription': sanitizedJobDescription,
            }