import os
import sys
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

SCRAPY_PROJECT_FOLDER = 'MultiwebsiteScraper'
SPIDERS = ["linkedin", "kariyerNet", "TechCareer", "indeed_html", "jooble"]

def run_spiders():
    for spider in SPIDERS:
        print(f"{spider} is now running...")

        if spider == "jooble":
            command = f"cd {SCRAPY_PROJECT_FOLDER} && scrapy crawl {spider} && scrapy crawl detail_worker"
        else:
            command = f"cd {SCRAPY_PROJECT_FOLDER} && scrapy crawl {spider}"

        exit_code = os.system(command)

        if exit_code == 0:
            print(f"{spider} is now finished its job...")
        else:
            print(f"An error occured while {spider} is working (Exit Code: {exit_code})")
    
    print("Scraping process is finished. Waiting until next run...")

if __name__ == '__main__':
    scheduler = BlockingScheduler()
    
    scheduler.add_job(run_spiders, 'cron', day='*/2', hour=3, minute=0)

    print("Automation system is ready. Waiting for APScheduler...")

    run_spiders()

    try:
        scheduler.start()
    
    except (KeyboardInterrupt, SystemExit):
        print("Automation is stopped!")