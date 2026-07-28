import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime, timedelta
import os

from MultiwebsiteScraper.models import Base

# PAGE TITLE
st.set_page_config(page_title="Job Applications Dasboard", layout="wide", page_icon="docs/logo.png")

#######################
# DATABASE CONNECTION #
#######################
def get_engine():
    """
    DATABASE_URL is required - there is no fallback with credentials in it.

    The previous default embedded a real password, which meant the password
    lived in the repository (and in its history, since the repo is public) and
    that a misconfigured deployment would quietly connect somewhere unintended
    instead of failing. Set it in .env locally, or as an environment variable
    in Coolify.
    """
    db_connection_str = os.getenv("DATABASE_URL")
    if not db_connection_str:
        st.error(
            "DATABASE_URL is not set. Add it to .env for local runs, or to the "
            "environment variables of this service in Coolify. Format:\n\n"
            "`postgresql+psycopg2://user:password@host:5432/dbname`"
        )
        st.stop()
    return create_engine(db_connection_str)

@st.cache_data(ttl=600)
def load_data():
    engine = get_engine()

    Base.metadata.create_all(engine)

    # Two independent hides, deliberately kept apart:
    #   is_active     - the classifier's soft delete (wrong field)
    #   duplicate_of  - the same job advertised on a second board
    # Neither deletes anything; both are one UPDATE away from reversal.
    query = (
        "SELECT * FROM job_posts "
        "WHERE is_active AND duplicate_of IS NULL "
        "ORDER BY created_at DESC"
    )
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

# The job types actually being looked for. Everything the scrapers find is
# still stored - postings disappear from the sites within weeks and cannot be
# fetched again, so we keep the data and narrow the view instead.
PREFERRED_JOB_TYPES = ["Internship", "Part-Time"]
default_job_types = [t for t in PREFERRED_JOB_TYPES if t in job_type_list] or job_type_list

selected_job_types = st.sidebar.multiselect(
    "Job type", job_type_list, default=default_job_types
)
if set(selected_job_types) != set(job_type_list):
    st.sidebar.caption(
        f"{len(job_type_list) - len(selected_job_types)} tip gizli - "
        "hepsini görmek için yukarıdan ekleyin."
    )

####################################################
# FIELD, AS DECIDED BY THE CLASSIFIER              #
####################################################
'''
    Two rules here, and the second one is the important one.

    Default to it + general_program: the whole point of the classifier is that
    the board should show software work, and general_program stays because
    "Intern" at UPS could still turn out to be software - the employer has not
    said yet.

    Unclassified rows (job_category IS NULL) stay VISIBLE no matter what the
    filter says. If the LLM API is down, or a crawl finished and the classify
    step failed, the postings are still real and the board must not be empty.
    A silent blank dashboard is a worse failure than a few unsorted rows.
'''
PREFERRED_CATEGORIES = ["it", "general_program"]
CATEGORY_LABELS = {
    "it": "Yazılım / IT",
    "general_program": "Genel staj programı",
}

category_list = [c for c in df["job_category"].dropna().unique().tolist()]
if category_list:
    default_categories = [
        c for c in PREFERRED_CATEGORIES if c in category_list
    ] or category_list

    selected_categories = st.sidebar.multiselect(
        "Alan",
        category_list,
        default=default_categories,
        format_func=lambda c: CATEGORY_LABELS.get(c, c),
    )
    category_mask = df["job_category"].isin(selected_categories) | df["job_category"].isna()
else:
    category_mask = pd.Series(True, index=df.index)

unclassified_count = int(df["job_category"].isna().sum())
if unclassified_count:
    st.sidebar.warning(
        f"{unclassified_count} ilan henüz sınıflandırılmadı - filtreden "
        "bağımsız olarak gösteriliyor."
    )

filtered_df = df[
    df['source_site'].isin(selected_sites)
    & df['job_type'].isin(selected_job_types)
    & category_mask
]

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

# category_reason is shown on purpose: the classifier's verdict should be
# arguable, not silent. A posting sitting in the wrong bucket is obvious the
# moment its reason reads wrong.
display_columns = [
    "job_title", "company", "location", "source_site", "created_at",
    "job_type", "job_category", "category_reason", "url",
]

st.dataframe(
    filtered_df[display_columns],
    column_config={
        "url": st.column_config.LinkColumn("Application URL"),
        "created_at": st.column_config.DatetimeColumn("Date", format="D MMM YYYY, HH:mm"),
        "job_category": st.column_config.TextColumn("Alan"),
        "category_reason": st.column_config.TextColumn("Neden", width="large"),
    },
    width= "stretch",
    hide_index=True
)