from itemadapter import ItemAdapter

from sqlalchemy.orm import sessionmaker
from .models import JobPost, db_connect, create_table
import re

# Job Type Normalization Mapping Tablosu
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
    
    # Contract Aliases
    'contract': 'Contract',
    'contract work': 'Contract',
    'kontrat': 'Contract',
    'sözleşmeli': 'Contract',
    'sözleşmeli çalışan': 'Contract',
    'temporary': 'Contract',
    'freelance': 'Freelance',
    'freelancer': 'Freelance',
    
    # Remote Work
    'remote': 'Remote',
    'remote work': 'Remote',
    'uzaktan çalışma': 'Remote',
    'uzaktan': 'Remote',
}

def normalize_job_type(job_type):
    """
    Job type'ı standart formata dönüştürür.
    
    Örneğin:
    - "FULL-TIME" -> "Full-Time"
    - "tam zamanlı" -> "Full-Time"
    - "Fulltime" -> "Full-Time"
    - Tanımlanmayan değerler -> "Other"
    """
    if not job_type or not isinstance(job_type, str):
        return "Other"
    
    # Boşlukları ve başı-sonunu temizle, küçük harfe dönüştür
    cleaned = job_type.strip().lower()
    
    # Mapping tablosunda varsa döndür
    if cleaned in JOB_TYPE_MAPPING:
        return JOB_TYPE_MAPPING[cleaned]
    
    # Eğer hiçbir alias eşleşmezse "Other" döndür
    return "Other"

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
            
            existing_job = session.query(JobPost).filter_by(url=item.get('url')).first()

            if existing_job:
                existing_job.job_title = item.get('job_title')
                existing_job.company = item.get('company')
                existing_job.location = item.get('location')
                existing_job.job_description = item.get('job_description')
                existing_job.job_type = normalized_job_type

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
                    job_type = normalized_job_type,
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
                