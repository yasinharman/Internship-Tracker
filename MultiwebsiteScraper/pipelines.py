from itemadapter import ItemAdapter
from sqlalchemy.orm import sessionmaker
from .models import JobPost, db_connect, create_table
import re

########################################
# JOB TYPE DATA NORMALIZATION MAPPING TABLE #
########################################
JOB_TYPE_MAPPING = {
    # Full-Time Aliases
    'full-time': 'Full-Time',
    'fulltime': 'Full-Time',
    'full time': 'Full-Time',
    'tam zamanlı': 'Full-Time',
    'tamzamanlı': 'Full-Time',
    'tam-zamanlı': 'Full-Time',
    'ft': 'Full-Time',
    'permanent': 'Full-Time',
    'permanent job': 'Full-Time',
    'sürekli': 'Full-Time',
    
    # Part-Time Aliases
    'part-time': 'Part-Time',
    'parttime': 'Part-Time',
    'part time': 'Part-Time',
    'yarı zamanlı': 'Part-Time',
    'yarızamanlı': 'Part-Time',
    'yarı-zamanlı': 'Part-Time',
    'pt': 'Part-Time',
    
    # Internship Aliases
    'internship': 'Internship',
    'intern': 'Internship',
    'staj': 'Internship',
    'stajyerlik': 'Internship',
    'stajyer': 'Internship',
    
    # Contract Aliases
    'contract': 'Contract',
    'contract work': 'Contract',
    'kontrat': 'Contract',
    'sözleşmeli': 'Contract',
    'sözleşmeli çalışan': 'Contract',
    'temporary': 'Contract',
    'freelance': 'Freelance',
    'freelancer': 'Freelance',
    'serbest zamanlı': 'Freelance',
    'geçici': 'Temporary',
    'proje bazlı': 'Contract',
    
    # Remote Work
    'remote': 'Remote',
    'remote work': 'Remote',
    'uzaktan çalışma': 'Remote',
    'uzaktan': 'Remote',
    'uzaktan / remote': 'Remote',
}

###################################################
# NORMALIZING THE JOB TYPE BY USING THIS FUNCTION #
###################################################
def normalize_job_type(job_type):

    if not job_type or not isinstance(job_type, str):
        return "Other"
    
    cleaned = job_type.strip().lower()
    
    if cleaned in JOB_TYPE_MAPPING:
        return JOB_TYPE_MAPPING[cleaned]
    
    return "Other"

#################################
# PIPELINE TO POSTGRES DATABASE #
#################################
class JobScraperPipeline:
    def __init__(self):
        engine = db_connect()

        create_table(engine)
        self.Session = sessionmaker(bind=engine)

    def process_item(self, item, spider):

        session = self.Session()

        try:
            # Job type normalization
            normalized_job_type = normalize_job_type(item.get('job_type'))
            
            # If the job application is already in the database we are updating its data if there is any difference
            existing_job = session.query(JobPost).filter_by(url=item.get('url')).first()

            if existing_job:
                existing_job.job_title = item.get('job_title')
                existing_job.company = item.get('company')
                existing_job.location = item.get('location')
                existing_job.job_description = item.get('job_description')
                existing_job.job_type = normalized_job_type

                existing_job.is_active = True

                spider.logger.info(f"Existing job post updated: {item.get('url')}")
            
            # If the job application is not in the database we are adding its data to database
            else:
                new_job = JobPost(
                    job_title = item.get('job_title'),
                    company = item.get('company'),
                    location = item.get('location'),
                    job_description = item.get('job_description'),
                    url = item.get('url'),
                    source_site = item.get('source_site'),
                    job_type = normalized_job_type,
                    # For created_at and is_active fields we created default values
                )
                session.add(new_job)
                spider.logger.info(f"New job application added.")
            
            session.commit()
        
        # Error handling
        except Exception as e:
            session.rollback() # If any error occurs while data was going through pipeline program rolls back the changes to not mess up the database.
            spider.logger.error(f"Some error occured while job application was being added to database: {e}")
        
        # We are ending the session to not keep our database busy
        finally:
            session.close() # To prevent "Too many connections error"
        
        # We are returning the item to see the data on the terminal
        return item
                