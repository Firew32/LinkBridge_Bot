from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, DateTime, Text, BigInteger
from dotenv import load_dotenv
import os
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

# Database connection string
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

try:
    # Initialize SQLAlchemy engine
    engine = create_engine(DATABASE_URL)
    meta = MetaData()

    # Drop existing table
    logger.info("Dropping existing table...")
    with engine.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS user_linkedin")
        conn.commit()

    # Create new table with profile_picture_url column
    linkedin_table = Table(
        'user_linkedin', meta,
        Column('id', Integer, primary_key=True),
        Column('linkedin_url', String, unique=True, nullable=False),
        Column('telegram_user_id', BigInteger, nullable=False),
        Column('full_name', String),
        Column('headline', String),
        Column('location', String),
        Column('current_company', String),
        Column('summary', Text),
        Column('profile_picture_url', String),
        Column('created_at', DateTime, default=datetime.utcnow),
        Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    )

    # Create the table
    meta.create_all(engine)
    logger.info("Database table updated successfully!")

except Exception as e:
    logger.error(f"Error updating database: {str(e)}")
    raise 