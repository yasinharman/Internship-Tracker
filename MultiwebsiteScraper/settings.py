import random
import sys
import asyncio

# Windows kullanıyorsan Event Loop politikasını değiştir
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
# Scrapy settings for MultiwebsiteScraper project
#
# For simplicity, this file contains only settings considered important or
# commonly used. You can find more settings consulting the documentation:
#
#     https://docs.scrapy.org/en/latest/topics/settings.html
#     https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
#     https://docs.scrapy.org/en/latest/topics/spider-middleware.html

BOT_NAME = "MultiwebsiteScraper"

# USER_AGENT = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0"

SPIDER_MODULES = ["MultiwebsiteScraper.spiders"]
NEWSPIDER_MODULE = "MultiwebsiteScraper.spiders"

ADDONS = {}

# DOWNLOAD_HANDLERS = { #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!#
#     "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
#     "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
# }

# TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

DOWNLOAD_HANDLERS = {
    'file': 'scrapy.core.downloader.handlers.file.FileDownloadHandler',
    'http': 'scrapy.core.downloader.handlers.http.HTTPDownloadHandler',
    'https': 'scrapy.core.downloader.handlers.http.HTTPDownloadHandler',
    's3': 'scrapy.core.downloader.handlers.s3.S3DownloadHandler',
    'ftp': 'scrapy.core.downloader.handlers.ftp.FTPDownloadHandler',
    'data': 'scrapy.core.downloader.handlers.datauri.DataURIDownloadHandler',
}

PLAYWRIGHT_BROWSER_TYPE = "chromium"
# PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = "/opt/google/chrome/google-chrome"

PLAYWRIGHT_LAUNCH_OPTIONS = { #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!#
    "headless": False,
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        # "--disable-web-security",
        # "--disable-features=VizDisplayCompositor",
        # "--disable-infobars",  # ← otomasyon bannerını kaldırır
        # "--start-maximized",   # ← gerçek kullanıcı gibi tam ekran aç
        # "--disable-extensions" # ← extension yokmuş gibi davran
    ]

}

# Obey robots.txt rules
ROBOTSTXT_OBEY = False

# Concurrency and throttling settings
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 3  
PLAYWRIGHT_MAX_CONTEXTS = 1 

CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1 #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!#
CONCURRENT_REQUESTS_PER_IP = 0
DOWNLOAD_DELAY = 3 #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!#
RANDOMIZE_DOWNLOAD_DELAY = True

# Disable cookies (enabled by default)
COOKIES_ENABLED = True

# Disable Telnet Console (enabled by default)
#TELNETCONSOLE_ENABLED = False

# Override the default request headers:
#DEFAULT_REQUEST_HEADERS = {
#    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#    "Accept-Language": "en",
#}

# Enable or disable spider middlewares
# See https://docs.scrapy.org/en/latest/topics/spider-middleware.html
#SPIDER_MIDDLEWARES = {
#    "MultiwebsiteScraper.middlewares.MultiwebsitescraperSpiderMiddleware": 543,
#}

# Enable or disable downloader middlewares
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
DOWNLOADER_MIDDLEWARES = {
    # 'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
    # 'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400,
}

# Enable or disable extensions
# See https://docs.scrapy.org/en/latest/topics/extensions.html
# EXTENSIONS = {
#     'scrapeops_scrapy.extension.ScrapeOpsMonitor': 500, #IMPORTANT FOR REQUEST MONITORING
# }

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
#ITEM_PIPELINES = {
#    "MultiwebsiteScraper.pipelines.MultiwebsitescraperPipeline": 300,
#}

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html
#AUTOTHROTTLE_ENABLED = True
# The initial download delay
#AUTOTHROTTLE_START_DELAY = 5
# The maximum download delay to be set in case of high latencies
#AUTOTHROTTLE_MAX_DELAY = 60
# The average number of requests Scrapy should be sending in parallel to
# each remote server
#AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
# Enable showing throttling stats for every response received:
#AUTOTHROTTLE_DEBUG = False

# Enable and configure HTTP caching (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#httpcache-middleware-settings
#HTTPCACHE_ENABLED = True
#HTTPCACHE_EXPIRATION_SECS = 0
#HTTPCACHE_DIR = "httpcache"
#HTTPCACHE_IGNORE_HTTP_CODES = []
#HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# Set settings whose default value is deprecated to a future-proof value
FEED_EXPORT_ENCODING = "utf-8"
