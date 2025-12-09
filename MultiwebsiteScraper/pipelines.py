from itemadapter import ItemAdapter

from sqlalchemy.orm import sessionmaker
from .models import JobPost, db_connect, create_table

class JobScraperPipeline:
    def __init__(self):
        engine = db_connect()

        create_table(engine)

        self.Session = sessionmaker(bind=engine)

    def process_item(self, item, spider):

        session = self.Session()

        try:
            existing_job = session.query(JobPost).filter_by(url=item.get('url')).first()

            if existing_job:
                existing_job.job_title = item.get('job_title')
                existing_job.company = item.get('company')
                existing_job.location = item.get('location')
                existing_job.job_description = item.get('job_description')
                existing_job.job_type = item.get('job_type')

                existing_job.is_active = True

                spider.logger.info(f"Existing job post updated: {item.get('url')}")
            
            else:
                new_job = JobPost(
                    job_title = item.get('job_title'),
                    company = item.get('company'),
                    location = item.get('location'),
                    job_description = item.get('job_description'),
                    url = item.get('url'),
                    source_site = item.get('source_site'),
                    job_type = item.get('job_type'),
                    # For created_at and is_active fields we created default values
                )
                session.add(new_job)
                spider.logger.info(f"New job application added.")
            
            session.commit()
        
        except Exception as e:
            session.rollback()
            spider.logger.error(f"Some error occured while job application was being added to database: {e}")
        
        finally:
            session.close()
        
        return item
                