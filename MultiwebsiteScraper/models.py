################
# ADD PASSWORD #
################

from sqlalchemy import create_engine, Integer, String, Boolean, Column, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

# WE ARE USING 'Base' INSIDE OF OUR CLASSES TO INDICATE THAT WE ARE CREATING A SQL TABLE INSIDE THE CLASS
Base = declarative_base()

###################################################################
# CREATED OUR TABLE'S STRUCTURE ON THE DATABASE USING SQL ALCHEMY #
###################################################################
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

##############################
# CONNECTION TO THE DATABASE #
##############################
def db_connect():
    return create_engine("postgresql+psycopg2://postgres:PASSWORD@localhost:5432/job_applications_db")

# FUNCTION TO CREATE TABLE
def create_table(engine):
    Base.metadata.create_all(engine)