# Scrapy settings for the tku project

BOT_NAME = "tku"
SPIDER_MODULES = ["tku.spiders"]
NEWSPIDER_MODULE = "tku.spiders"
ADDONS = {}

ROBOTSTXT_OBEY = True
USER_AGENT = "TKU-RAG-student-project (https://github.com/10xivbl/TKU-CHATBOT)"

# Request speed
DOWNLOAD_DELAY = 1.0
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

# Timeout and retries
DOWNLOAD_TIMEOUT = 60
RETRY_TIMES = 2

# Concurrency
CONCURRENT_REQUESTS_PER_DOMAIN = 2
CONCURRENT_REQUESTS = 8

# Response limits
DOWNLOAD_MAXSIZE = 100 * 1024 * 1024

# No link following: the spider is a plain scrapy.Spider and only fetches the
# URLs it is given. (Do NOT set DEPTH_LIMIT = 0 -- in Scrapy that means unlimited.)

LOG_LEVEL = "INFO"
FEED_EXPORT_ENCODING = "utf-8"

# Pages are stored in seen.db (one row per URL). Use export.py to produce JSON.
ITEM_PIPELINES = {
    "tku.pipelines.CleanPipeline": 300,
    "tku.pipelines.ChangePipeline": 400,
}
