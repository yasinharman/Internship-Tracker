import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime, timedelta
import os

from MultiwebsiteScraper.models import Base

# PAGE TITLE
st.set_page_config(page_title="Job Applications Dasboard", layout="wide")

#######################
# DATABASE CONNECTION #
#######################
def get_engine():
    db_connection_str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:Mehperya16@localhost:5432/job_applications_db"
    )
    return create_engine(db_connection_str)

@st.cache_data(ttl=600)
def load_data():
    engine = get_engine()

    Base.metadata.create_all(engine)

    query = "SELECT * FROM job_posts ORDER BY created_at DESC"
    df = pd.read_sql(query, engine)

    if not df.empty:
        df['created_at'] = pd.to_datetime(df["created_at"])
    return df

try:
    df = load_data()

except Exception as e:
    st.error(f"An error occured while connecting to database: {e}")
    st.stop()

if df.empty:
    st.title("Current Job Postings")
    st.info("Henüz veri yok. Scraper'ın ilk çalışmasını bekleyin; tamamlandığında bu sayfa otomatik dolar.")
    st.stop()

###########
# SIDEBAR #
###########
st.sidebar.header("Filter")

site_list = df["source_site"].unique().tolist()
selected_sites = st.sidebar.multiselect("Source site", site_list, default=site_list)

job_type_list = df["job_type"].unique().tolist()
selected_job_types = st.sidebar.multiselect("Job type", job_type_list, default=job_type_list)

filtered_df = df[df['source_site'].isin(selected_sites) & df['job_type'].isin(selected_job_types)]

########################
# CURRENT JOB POSTINGS #
########################
st.title("Current Job Postings")

col1, col2, col3, = st.columns(3)

total_jobs = len(filtered_df)
col1.metric("Total Job Application Count", total_jobs)

today = datetime.now().date()
jobs_today = len(filtered_df[filtered_df['created_at'].dt.date == today])
col2.metric("Added Today", jobs_today, delta=f"{jobs_today} new")

total_companies = filtered_df["company"].nunique()
col3.metric("Different Company Count", total_companies)

st.markdown("---")

###########################################
# DISTRIBUTION BY SITES & JOB TYPE CHARTS #
###########################################
col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.subheader("Distribution by sites")
    site_counts = filtered_df['source_site'].value_counts()
    st.bar_chart(site_counts)

with col_chart2:
    st.subheader("Job Type")
    if 'job_type' in filtered_df.columns and not filtered_df["job_type"].isnull().all():
        type_counts = filtered_df['job_type'].value_counts()
        st.bar_chart(type_counts)

    else:
        st.info("There isn't any job applications with the selected job type.")

###########################
# RECENT JOB APPLICATIONS #
###########################
st.subheader("Recent Applications")

display_columns = ["job_title", "company", "location", "source_site", "created_at", "job_type","url"]

st.dataframe(
    filtered_df[display_columns],
    column_config={
        "url": st.column_config.LinkColumn("Application URL"),
        "created_at": st.column_config.DatetimeColumn("Date", format="D MMM YYYY, HH:mm")
    },
    width= "stretch",
    hide_index=True
)