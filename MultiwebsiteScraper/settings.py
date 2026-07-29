import os

from dotenv import load_dotenv

# Load environment variables from .env file (if present)
load_dotenv()

SCRAPEOPS_API_KEY = os.getenv("SCRAPEOPS_API_KEY")

BOT_NAME = "MultiwebsiteScraper"

SPIDER_MODULES = ["MultiwebsiteScraper.spiders"]
NEWSPIDER_MODULE = "MultiwebsiteScraper.spiders"

ADDONS = {}

'''
    Playwright is gone. It was only ever used by the old TechCareer spider,
    which rendered the page to reach data that turned out to be sitting in the
    HTML as JSON all along. Removing it takes ~500MB and the slowest, most
    failure-prone step out of the Docker build.

    Every spider now makes plain HTTP requests: kariyer.net is parsed from
    server-rendered markup, TechCareer from its Next.js data endpoint, Indeed
    from the JSON embedded in its search page.
'''
DOWNLOAD_HANDLERS = {
    'file': 'scrapy.core.downloader.handlers.file.FileDownloadHandler',
    'http': 'scrapy.core.downloader.handlers.http.HTTPDownloadHandler',
    'https': 'scrapy.core.downloader.handlers.http.HTTPDownloadHandler',
    's3': 'scrapy.core.downloader.handlers.s3.S3DownloadHandler',
    'ftp': 'scrapy.core.downloader.handlers.ftp.FTPDownloadHandler',
    'data': 'scrapy.core.downloader.handlers.datauri.DataURIDownloadHandler',
}

# Obey robots.txt rules
ROBOTSTXT_OBEY = False

# Concurrency and throttling settings
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1 #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!#
CONCURRENT_REQUESTS_PER_IP = 0
DOWNLOAD_DELAY = 3 #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!#
RANDOMIZE_DOWNLOAD_DELAY = True

# Cookies are REQUIRED by the JSON API spiders: they load a normal page first
# and the session cookies it sets are what the API endpoints check for.
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

##########################################################
# DOWNLOADER MIDDLEWARES FOR THE JSON API SCRAPING MODE  #
##########################################################
'''
    590 - BlockDetectionMiddleware sees responses BEFORE RetryMiddleware (550),
          because Scrapy walks the response path in decreasing priority. A 403
          therefore triggers an IP escalation instead of a blind retry from the
          same address.
    725 - ResidentialProxyMiddleware runs before Scrapy's HttpProxyMiddleware
          (750), which converts the credentials in our proxy URL into a
          Proxy-Authorization header.

    Both self-disable when PROXY_MODE=off or no IPRoyal credentials are set,
    so local development goes out direct with no extra configuration.
'''
DOWNLOADER_MIDDLEWARES = {
    "MultiwebsiteScraper.api_middlewares.BlockDetectionMiddleware": 590,
    "MultiwebsiteScraper.api_middlewares.ResidentialProxyMiddleware": 725,
    # 'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
    # 'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400,
}

# How many times one request may climb the escalation ladder
# (direct -> proxy -> fresh proxy IP) before it is dropped.
PROXY_MAX_ESCALATIONS = 3

# How many refusals one domain may hand us in a single run before we stop
# sending to it altogether. Blocks are not free: a burst of them moves the
# exit address into a bucket that takes minutes to climb back out of, so a
# crawl that keeps knocking damages the next one as well as itself. Eight is
# room for a bad patch, not room for four searches to grind through every
# impersonation candidate. See BlockDetectionMiddleware._over_budget.
DOMAIN_BLOCK_BUDGET = 8

# Residential bandwidth is metered, so give up on genuinely dead requests
# rather than paying to retry them forever.
RETRY_ENABLED = True
RETRY_TIMES = 2
DOWNLOAD_TIMEOUT = 60

# Enable or disable extensions
# See https://docs.scrapy.org/en/latest/topics/extensions.html
# EXTENSIONS = {
#     'scrapeops_scrapy.extension.ScrapeOpsMonitor': 500, #IMPORTANT FOR REQUEST MONITORINGo
# }

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
ITEM_PIPELINES = {
   "MultiwebsiteScraper.pipelines.JobScraperPipeline": 300,
}

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
