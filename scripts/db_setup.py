from sqlalchemy import create_engine, Table, Column, Integer, String, MetaData,BigInteger
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

# Database connection string
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Initialize SQLAlchemy engine
engine = create_engine(DATABASE_URL)
meta = MetaData()


linkedin_table = Table(
    'user_linkedin', meta,
    Column('id', Integer, primary_key=True),
    Column('linkedin_url', String, unique=True, nullable=False),
    Column('telegram_user_id', BigInteger, nullable=False)  # Use BigInteger here
)


# Create the table in the database
meta.create_all(engine)
print("Database and table created successfully.")

