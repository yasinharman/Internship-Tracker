from sqlalchemy import create_engine, Integer, String, Boolean, Column, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

Base = declarative_base()

class JobPost(Base):
    __tablename__ = "job_posts"
    id = Column(Integer, primary_key=True)
    
    job_title = Column(String, nullable=False)
    
    company = Column(String)
    
    location = Column(String)
    
    job_description = Column(Text)
    
    url = Column(String, unique=True, nullable=False)
    
    source_site = Column(String, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    job_type = Column(String)

def db_connect():
    return create_engine("postgresql+psycopg2://postgres:Mehperya16@localhost:5432/job_applications_db")

def create_table(engine):
    Base.metadata.create_all(engine)