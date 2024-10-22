from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import logging
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, insert, select, Table, MetaData
from sqlalchemy.exc import IntegrityError


# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

# Database connection string
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Initialize SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Define handlers
async def start(update: Update, context) -> None:
    await update.message.reply_text("Welcome! Send me your LinkedIn profile link.")

async def handle_message(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text
    if "linkedin.com" in user_message:  # Basic validation for LinkedIn URLs
        try:
            # Insert LinkedIn URL into the database with transaction handling
            with engine.begin() as conn:
                meta = MetaData()
                linkedin_table = Table('user_linkedin', meta, autoload_with=engine)
                insert_statement = insert(linkedin_table).values(linkedin_url=user_message)
                conn.execute(insert_statement)

            # Send confirmation message
            await update.message.reply_text("Thank you! Your LinkedIn profile has been saved.")

            # Fetch all LinkedIn profiles except the newly added one
            with engine.connect() as conn:
                stmt = select(linkedin_table.c.linkedin_url).where(linkedin_table.c.linkedin_url != user_message)
                result = conn.execute(stmt)
                linkedin_list = [row[0] for row in result]  # Access the first column of each row

            # Send the list of other LinkedIn profiles
            if linkedin_list:
                linkedin_str = "\n".join(linkedin_list)
                await update.message.reply_text(f"Here are the LinkedIn profiles of others:\n{linkedin_str}")
            else:
                await update.message.reply_text("You are the first one to register!")

        # Handle duplicate LinkedIn URLs
        except IntegrityError as e:
            if "duplicate key value violates unique constraint" in str(e.orig):
                await update.message.reply_text("Your LinkedIn profile is already saved.")

                # Fetch and send the list of other LinkedIn profiles
                with engine.connect() as conn:
                    stmt = select(linkedin_table.c.linkedin_url).where(linkedin_table.c.linkedin_url != user_message)
                    result = conn.execute(stmt)
                    linkedin_list = [row[0] for row in result]  # Access the first column of each row

                if linkedin_list:
                    linkedin_str = "\n".join(linkedin_list)
                    await update.message.reply_text(f"Here are the LinkedIn profiles of others:\n{linkedin_str}")
                else:
                    await update.message.reply_text("You are the first one to register!")
            else:
                await update.message.reply_text(f"Error saving your profile: {e}")
                print(f"Database Error: {e}")
    else:
        await update.message.reply_text("Please send a valid LinkedIn URL.")


# Error handling
async def error_handler(update: object, context: object) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

def main():
    # Create the Application and pass your bot's token
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register command and message handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Register the error handler
    application.add_error_handler(error_handler)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
