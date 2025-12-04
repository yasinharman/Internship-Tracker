import sys
import asyncio
from scrapy.cmdline import execute

# Windows Event Loop Düzeltmesi
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == '__main__':
    # Terminalden gelen argümanları Scrapy'ye aktar
    # Kullanıcı ne yazdıysa (crawl techcareer -O output.json) aynen çalıştırır
    execute()