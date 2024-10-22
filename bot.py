from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import logging
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, insert, select, Table, MetaData, Column, Integer, String
from sqlalchemy.exc import IntegrityError

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

# Validate environment variables
if not all([TELEGRAM_BOT_TOKEN, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
    raise ValueError("Some environment variables are missing.")

# Database connection string
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Initialize SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize metadata
meta = MetaData()

# Define the LinkedIn user table
linkedin_table = Table(
    'user_linkedin', meta,
    Column('id', Integer, primary_key=True),
    Column('linkedin_url', String, unique=True, nullable=False),
    Column('telegram_user_id', Integer, nullable=False)
)

# Initialize Flask app
app = Flask(__name__)

# Define handlers
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Welcome! Send me your LinkedIn profile link.")

async def handle_message(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text
    telegram_user_id = update.message.from_user.id

    if "linkedin.com" in user_message:
        try:
            with engine.begin() as conn:
                insert_statement = insert(linkedin_table).values(linkedin_url=user_message, telegram_user_id=telegram_user_id)
                conn.execute(insert_statement)

            await update.message.reply_text("Thank you! Your LinkedIn profile has been saved.")
            await send_linkedin_profiles(update, user_message)
            await notify_users_of_new_profile(context, user_message, telegram_user_id)

        except IntegrityError as e:
            if "duplicate key value violates unique constraint" in str(e.orig):
                await update.message.reply_text("Your LinkedIn profile is already saved.")
                await send_linkedin_profiles(update, user_message)
            else:
                await update.message.reply_text(f"Error saving your profile: {e}")
                logger.error(f"Database Error: {e}")
    else:
        await update.message.reply_text("Please send a valid LinkedIn URL.")

async def send_linkedin_profiles(update: Update, user_message: str) -> None:
    with engine.connect() as conn:
        stmt = select(linkedin_table.c.linkedin_url).where(linkedin_table.c.linkedin_url != user_message)
        result = conn.execute(stmt)
        linkedin_list = [row[0] for row in result]

    if linkedin_list:
        linkedin_str = "\n".join(linkedin_list)
        await update.message.reply_text(f"Here are the LinkedIn profiles of others:\n{linkedin_str}")
    else:
        await update.message.reply_text("You are the first one to register!")

async def notify_users_of_new_profile(context: CallbackContext, linkedin_url: str, new_user_id: int) -> None:
    with engine.connect() as conn:
        stmt = select(linkedin_table.c.telegram_user_id).where(linkedin_table.c.telegram_user_id != new_user_id)
        result = conn.execute(stmt)
        registered_users = [row[0] for row in result]

    for user_id in registered_users:
        try:
            await context.bot.send_message(chat_id=user_id, text=f"A new LinkedIn profile has been registered: {linkedin_url}")
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

# Error handling
async def error_handler(update: object, context: CallbackContext) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# Define a root route
@app.route('/', methods=['GET'])
def home():
    return "Welcome to the LinkedIn Profile Bot! Use /set_webhook to set up the webhook.", 200

# Initialize the Telegram application
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_error_handler(error_handler)

# Define the Flask route for Telegram webhook
@app.route(f'/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    application.update_queue.put_nowait(update)
    return "OK", 200

# Function to set the webhook (optional)
@app.route('/set_webhook', methods=['GET', 'POST'])
def set_webhook():
    webhook_url = f"https://your-server-domain.com/{TELEGRAM_BOT_TOKEN}"
    application.bot.set_webhook(webhook_url)
    return "Webhook set successfully", 200

# Main function to run the Flask app
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
