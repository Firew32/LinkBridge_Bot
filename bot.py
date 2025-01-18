from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
import logging
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, insert, select, Table, MetaData, Column, Integer, String, DateTime, Text
from sqlalchemy.exc import IntegrityError
from collections import defaultdict
from datetime import datetime, timedelta
import requests
from io import BytesIO
from telegram import InputFile
from typing import Optional, Dict, Any, List
from sqlalchemy.sql import func, text
import asyncio
from linkedin_api import Linkedin
import json
import logging.handlers
from config.logging_config import setup_logging
from time import sleep
import aiohttp
from sqlalchemy.sql import or_
import csv
import time
import telegram.error
import platform
import re
import sys
from contextlib import contextmanager
import fcntl



message_timestamps = defaultdict(list)

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
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    # Fallback to constructing URL from individual credentials
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    DB_HOST = os.getenv('DB_HOST')
    DB_PORT = os.getenv('DB_PORT')
    DB_NAME = os.getenv('DB_NAME')
    
    if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
        raise ValueError("Database configuration is missing")
        
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Initialize SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Configure logging with rotation
log_file = os.getenv('LOG_FILE', 'logs/bot.log')
os.makedirs(os.path.dirname(log_file), exist_ok=True)

handler = logging.handlers.RotatingFileHandler(
    log_file,
    maxBytes=1024 * 1024,  # 1MB
    backupCount=5
)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

logger = setup_logging(__name__)

# Initialize metadata
meta = MetaData()

# Define the LinkedIn user table
linkedin_table = Table(
    'user_linkedin', meta,
    Column('id', Integer, primary_key=True),
    Column('linkedin_url', String, unique=True, nullable=False),
    Column('telegram_user_id', Integer, nullable=False),
    Column('full_name', String),
    Column('headline', String),
    Column('location', String),
    Column('current_company', String),
    Column('summary', Text),
    Column('created_at', DateTime, default=datetime.utcnow),
    Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
)

# Add LinkedIn API initialization
try:
    logger.info("Initializing LinkedIn API...")
    LINKEDIN_USERNAME = os.getenv('LINKEDIN_USERNAME')
    LINKEDIN_PASSWORD = os.getenv('LINKEDIN_PASSWORD')
    
    if not all([LINKEDIN_USERNAME, LINKEDIN_PASSWORD]):
        logger.warning("LinkedIn credentials not found - bot will run without LinkedIn API features")
        api = None
    else:
        try:
            # Initialize API with basic authentication (removed unsupported parameters)
            api = Linkedin(
                LINKEDIN_USERNAME,
                LINKEDIN_PASSWORD
            )
            # Test the connection with a simple operation
            logger.info("Testing LinkedIn connection...")
            try:
                # Use a simpler test that's less likely to trigger security
                me = api.get_profile()
                if me:
                    logger.info("LinkedIn API initialized successfully")
                else:
                    raise Exception("Could not verify LinkedIn connection")
            except Exception as test_error:
                logger.error(f"LinkedIn API test failed: {str(test_error)}")
                api = None
                
        except Exception as api_error:
            if "CHALLENGE" in str(api_error):
                logger.warning("""
                LinkedIn requires additional verification. To fix this:
                1. Log in to LinkedIn in your browser with the same account
                2. Complete any security verification steps
                3. Make sure 2FA is disabled for this account
                4. Wait 15-30 minutes before trying again
                5. Consider using a different LinkedIn account
                Bot will continue without LinkedIn API features.
                """)
            else:
                logger.error(f"LinkedIn API initialization failed: {str(api_error)}", exc_info=True)
            api = None

except Exception as e:
    logger.error(f"Failed to initialize LinkedIn API: {str(e)}", exc_info=True)
    api = None

# Define handlers
async def get_main_keyboard():
    """Get the main keyboard markup"""
    keyboard = [
        [KeyboardButton("➕ Add Profile")],
        [KeyboardButton("📚 Help"), KeyboardButton("ℹ️ Status")],
        [KeyboardButton("❌ Delete Profile"), KeyboardButton("🔄 Update Profile")],
        [KeyboardButton("👥 View Users")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.message.from_user.id
        username = update.message.from_user.username
        logger.info(f"New user {user_id} (@{username}) started the bot")
        
        reply_markup = await get_main_keyboard()
        
        welcome_text = (
            "🌟 *Welcome to the LinkedIn Profile Sharing Bot!* 🌟\n\n"
            "Connect with professionals and share your LinkedIn profile easily.\n\n"
            "📝 *How to use:*\n"
            "• Share your LinkedIn profile URL\n"
            "• View other professionals' profiles\n"
            "• Get notified about new connections\n\n"
            "🔗 *Share your profile by sending a URL like:*\n"
            "`https://www.linkedin.com/in/username`\n\n"
            "Use the buttons below to navigate! 👇"
        )
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}", exc_info=True)
        await update.message.reply_text("Sorry, an error occurred. Please try again later.")

async def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_message = update.message.text
    logger.info(f"Received message from user {user_id}: {user_message}")
    
    # Handle button presses first
    if user_message in ["➕ Add Profile", "📚 Help", "ℹ️ Status", "❌ Delete Profile", "🔄 Update Profile", "👥 View Users"]:
        try:
            if user_message == "➕ Add Profile":
                await update.message.reply_text(
                    "Please send your LinkedIn profile URL.\n"
                    "Example: https://www.linkedin.com/in/username",
                    reply_markup=await get_main_keyboard()
                )
            elif user_message == "📚 Help":
                logger.info(f"Help button pressed by user {user_id}")
                await help_command(update, context)
            elif user_message == "ℹ️ Status":
                await status(update, context)
            elif user_message == "❌ Delete Profile":
                await delete_profile(update, context)
            elif user_message == "🔄 Update Profile":
                await update_profile(update, context)
            elif user_message == "👥 View Users":
                await show_user_list(update, context)
            return
        except Exception as e:
            logger.error(f"Error handling button press '{user_message}': {str(e)}", exc_info=True)
            await update.message.reply_text(
                "Sorry, there was an error processing your request.",
                reply_markup=await get_main_keyboard()
            )
            return

    # Handle delete confirmation
    if context.user_data.get('awaiting_delete_confirmation'):
        if user_message.lower() in ["yes", "✅ yes, delete my profile"]:
            try:
                with engine.begin() as conn:
                    result = conn.execute(
                        linkedin_table.delete().where(linkedin_table.c.telegram_user_id == user_id)
                    )
                    if result.rowcount > 0:
                        logger.info(f"Successfully deleted profile for user {user_id}")
                        # Reset to default keyboard
                        keyboard = [
                            [KeyboardButton("📚 Help"), KeyboardButton("ℹ️ Status")],
                            [KeyboardButton("❌ Delete Profile"), KeyboardButton("🔄 Update Profile")]
                        ]
                        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                        await update.message.reply_text(
                            "Your profile has been deleted.",
                            reply_markup=reply_markup
                        )
                    else:
                        logger.warning(f"No profile found to delete for user {user_id}")
                        await update.message.reply_text("No profile found to delete.")
            except Exception as e:
                logger.error(f"Error deleting profile for user {user_id}: {str(e)}", exc_info=True)
                await update.message.reply_text("Sorry, there was an error deleting your profile.")
        elif user_message.lower() in ["no", "❌ no, keep my profile"]:
            # Reset to default keyboard
            keyboard = [
                [KeyboardButton("📚 Help"), KeyboardButton("ℹ️ Status")],
                [KeyboardButton("❌ Delete Profile"), KeyboardButton("🔄 Update Profile")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "Profile deletion cancelled.",
                reply_markup=reply_markup
            )
        # Clear the awaiting confirmation state
        context.user_data.pop('awaiting_delete_confirmation', None)
        return

    # Handle LinkedIn URL processing
    if is_valid_linkedin_url(user_message):
        await process_linkedin_url(update, context, user_message)
    else:
        logger.warning(f"Invalid message received from user {user_id}: {user_message}")
        # Don't show the error message for button presses
        if not user_message.startswith(('📚', 'ℹ️', '❌', '🔄', '✅')):
            await update.message.reply_text(
                "Please send a valid LinkedIn profile URL or use the buttons below.\n"
                "Example URL: https://www.linkedin.com/in/username"
            )

async def process_linkedin_url(update: Update, context: CallbackContext, url: str) -> None:
    """Process LinkedIn URL submission"""
    user_id = update.message.from_user.id
    
    # Check rate limit
    if not await rate_limit_check(user_id):
        logger.warning(f"Rate limit exceeded for user {user_id}")
        await update.message.reply_text("You're sending too many messages. Please wait a moment.")
        return

    try:
        # Check if user already has a profile
        with engine.connect() as conn:
            existing_profile = conn.execute(
                select(linkedin_table).where(linkedin_table.c.telegram_user_id == user_id)
            ).first()
            
            if existing_profile:
                logger.warning(f"Duplicate LinkedIn URL from user {user_id}")
                await update.message.reply_text(
                    "You have already registered a LinkedIn profile.\n"
                    "Use /delete to remove your current profile first, or\n"
                    "Use /update to update your existing profile."
                )
                return

        # If no existing profile, proceed with profile creation
        profile_info = await fetch_linkedin_profile(url)
        
        # Insert the new profile
        with engine.begin() as conn:
            insert_data = {
                'linkedin_url': url,
                'telegram_user_id': user_id,
                'created_at': datetime.utcnow()
            }
            
            if profile_info:
                insert_data.update(profile_info)
                
            conn.execute(linkedin_table.insert(), insert_data)
            logger.info(f"Saved LinkedIn URL for user {user_id}")
            
        await update.message.reply_text("Your LinkedIn profile URL has been saved!")
        
        # Show other profiles and notify users
        await send_linkedin_profiles(update, url)
        await notify_users_of_new_profile(context, url, user_id)
        
    except IntegrityError:
        logger.warning(f"Duplicate LinkedIn URL from user {user_id}")
        await update.message.reply_text("This LinkedIn profile has already been registered.")
    except Exception as e:
        logger.error(f"Error processing LinkedIn URL: {str(e)}", exc_info=True)
        await update.message.reply_text("Sorry, there was an error processing your LinkedIn URL.")

async def send_linkedin_profiles(update: Update, user_message: str) -> None:
    """Send other LinkedIn profiles to the user in a structured format"""
    user_id = update.message.from_user.id
    logger.info(f"Fetching LinkedIn profiles for user {user_id}")
    
    try:
        with engine.connect() as conn:
            # Query all profiles except the current user's with all fields
            query = select(linkedin_table).where(
                linkedin_table.c.telegram_user_id != user_id
            )
            result = conn.execute(query)
            profiles = result.fetchall()
            
            if not profiles:
                logger.info(f"No other profiles to show to user {user_id}")
                await update.message.reply_text(
                    "You're the first one here! 🎉\n"
                    "Share your profile with others to grow the network."
                )
                return
            
            logger.info(f"Sending {len(profiles)} profiles to user {user_id}")
            
            # Send profiles one by one with formatted information
            for profile in profiles:
                profile_text = (
                    f"👤 *{profile.full_name or 'Name not available'}*\n"
                    f"{'✨ ' + profile.headline + chr(10) if profile.headline else ''}"
                    f"{'🏢 ' + profile.current_company + chr(10) if profile.current_company else ''}"
                    f"{'📍 ' + profile.location + chr(10) if profile.location else ''}"
                    f"\n🔗 [View Full Profile]({profile.linkedin_url})\n"
                    f"{'━' * 30}"
                )
                
                try:
                    await update.message.reply_text(
                        profile_text,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Error sending profile {profile.linkedin_url}: {str(e)}")
                    continue
                
            # Send summary message
            await update.message.reply_text(
                f"✨ Showing {len(profiles)} professional{'s' if len(profiles) > 1 else ''} "
                f"in your network.\n\n"
                "💡 Use /search to find specific profiles\n"
                "📊 Use /stats to see network statistics",
                parse_mode='Markdown'
            )
                
    except Exception as e:
        logger.error(f"Error fetching profiles for user {user_id}: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "Sorry, there was an error fetching other profiles."
        )

async def notify_users_of_new_profile(context: CallbackContext, linkedin_url: str, new_user_id: int) -> None:
    """Notify existing users about new profile with structured information"""
    try:
        with engine.connect() as conn:
            # Get the new user's profile information
            new_profile = conn.execute(
                select(linkedin_table).where(linkedin_table.c.telegram_user_id == new_user_id)
            ).first()
            
            if not new_profile:
                logger.error(f"Could not find profile for new user {new_user_id}")
                return
                
            # Get all other users
            stmt = select(linkedin_table.c.telegram_user_id).where(
                linkedin_table.c.telegram_user_id != new_user_id
            )
            result = conn.execute(stmt)
            registered_users = [row[0] for row in result]

            # Create notification message
            notification_text = (
                "🎉 *New Connection Alert!*\n\n"
                f"👤 *{new_profile.full_name or 'New Professional'}*\n"
                f"{'✨ ' + new_profile.headline + chr(10) if new_profile.headline else ''}"
                f"{'🏢 ' + new_profile.current_company + chr(10) if new_profile.current_company else ''}"
                f"{'📍 ' + new_profile.location + chr(10) if new_profile.location else ''}"
                f"\n🔗 [View Full Profile]({linkedin_url})\n\n"
                "Connect and expand your professional network! ✨"
            )

            # Notify each user
            for user_id in registered_users:
                try:
                    if new_profile.profile_picture_url:
                        try:
                            await context.bot.send_photo(
                                chat_id=user_id,
                                photo=new_profile.profile_picture_url,
                                caption=notification_text,
                                parse_mode='Markdown'
                            )
                        except Exception:
                            # Fallback to text-only if photo fails
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=notification_text,
                                parse_mode='Markdown',
                                disable_web_page_preview=True
                            )
                    else:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=notification_text,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                    logger.info(f"Notified user {user_id} about new profile")
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {e}")
                    
    except Exception as e:
        logger.error(f"Error in notify_users_of_new_profile: {str(e)}", exc_info=True)

async def rate_limit_check(user_id: int, limit: int = 5, window: int = 60) -> bool:
    current_time = datetime.now()
    timestamps = message_timestamps[user_id]
    
    # Remove timestamps older than the window
    timestamps = [ts for ts in timestamps if (current_time - ts).total_seconds() < window]
    message_timestamps[user_id] = timestamps
    
    # Check if user has exceeded rate limit
    if len(timestamps) >= limit:
        return False
    
    # Add new timestamp
    timestamps.append(current_time)
    return True


# Error handling
async def error_handler(update: object, context: CallbackContext) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, 'effective_chat'):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Sorry, an error occurred while processing your request."
        )



async def delete_profile(update: Update, context: CallbackContext) -> None:
    """Delete user's LinkedIn profile with confirmation"""
    user_id = update.message.from_user.id
    logger.info(f"Delete profile request from user {user_id}")
    
    try:
        # First check if user has a profile
        with engine.connect() as conn:
            result = conn.execute(
                select(linkedin_table).where(linkedin_table.c.telegram_user_id == user_id)
            ).first()
            
            if not result:
                logger.warning(f"No profile found to delete for user {user_id}")
                await update.message.reply_text("You don't have a registered profile.")
                return
        
        # Create confirmation keyboard
        keyboard = [
            [KeyboardButton("✅ Yes, delete my profile")],
            [KeyboardButton("❌ No, keep my profile")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        # Ask for confirmation
        await update.message.reply_text(
            "⚠️ *Are you sure you want to delete your LinkedIn profile?*\n"
            "This action cannot be undone.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Set user state to await confirmation
        context.user_data['awaiting_delete_confirmation'] = True
        
    except Exception as e:
        logger.error(f"Error in delete profile command: {str(e)}", exc_info=True)
        await update.message.reply_text("Sorry, there was an error processing your request.")

async def update_profile(update: Update, context: CallbackContext) -> None:
    """Update user's LinkedIn profile"""
    user_id = update.message.from_user.id
    logger.info(f"Profile update requested by user {user_id}")
    
    try:
        # Check if user has a profile
        with engine.connect() as conn:
            result = conn.execute(
                select(linkedin_table).where(linkedin_table.c.telegram_user_id == user_id)
            ).first()
            
            if not result:
                await update.message.reply_text(
                    "You don't have a registered profile yet.\n"
                    "Send your LinkedIn profile URL to register."
                )
                return
            
            # Show current profile and request new URL
            current_profile = (
                "Your current profile:\n\n"
                f"Name: {result.full_name or 'Not available'}\n"
                f"Headline: {result.headline or 'Not available'}\n"
                f"Company: {result.current_company or 'Not available'}\n"
                f"Location: {result.location or 'Not available'}\n\n"
                "To update your profile, send your LinkedIn URL again."
            )
            
            await update.message.reply_text(current_profile)
            
    except Exception as e:
        logger.error(f"Error in update profile command: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "Sorry, there was an error processing your request."
        )

ADMIN_IDS = [int(id_) for id_ in os.getenv('ADMIN_IDS', '').split(',') if id_]

async def admin_stats(update: Update, context: CallbackContext) -> None:
    if update.message.from_user.id not in ADMIN_IDS:
        return
    
    with engine.connect() as conn:
        total_users = conn.execute(select(func.count()).select_from(linkedin_table)).scalar()
        await update.message.reply_text(f"Total registered users: {total_users}")

async def help_command(update: Update, context: CallbackContext) -> None:
    """Show help information"""
    try:
        user_id = update.message.from_user.id
        logger.info(f"Help command requested by user {user_id}")
        
        help_text = (
            "🌟 *LinkedIn Profile Sharing Bot Help*\n\n"
            "*Basic Commands:*\n"
            "• Click '➕ Add Profile' to share your LinkedIn profile\n"
            "• Use '👥 View Users' to see other profiles\n"
            "• Use '🔄 Update Profile' to update your info\n"
            "• Use '❌ Delete Profile' to remove your profile\n\n"
            "*Additional Commands:*\n"
            "• /start \\- Start the bot\n"
            "• /help \\- Show this help message\n"
            "• /status \\- Check bot status\n"
            "• /search \\- Search profiles\n"
            "• /stats \\- View network statistics\n\n"
            "*Tips:*\n"
            "• Keep your profile up to date\n"
            "• Use professional profile pictures\n"
            "• Fill out your LinkedIn headline\n"
            "• Engage with other professionals\n\n"
            "Need help? Contact @alphityy"
        )
        
        logger.info("Sending help message...")
        await update.message.reply_text(
            help_text,
            parse_mode='MarkdownV2',  # Use MarkdownV2 for better compatibility
            reply_markup=await get_main_keyboard()
        )
        logger.info(f"Help message sent successfully to user {user_id}")
        
    except Exception as e:
        logger.error(f"Error in help command: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "Sorry, there was an error showing the help message. Please try /help again.",
            reply_markup=await get_main_keyboard()
        )

async def retry_linkedin_api(func: callable, *args, max_retries: int = 3, **kwargs) -> Optional[Any]:
    """Retry a LinkedIn API call with exponential backoff"""
    for attempt in range(max_retries):
        try:
            # Create a thread pool executor for the blocking call
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, lambda: func(*args, **kwargs))
            return result
        except Exception as e:
            if attempt == max_retries - 1:  # Last attempt
                raise
            wait_time = (2 ** attempt) * 1  # Exponential backoff: 1, 2, 4 seconds
            logger.warning(f"LinkedIn API call failed, retrying in {wait_time}s: {str(e)}")
            await asyncio.sleep(wait_time)

async def fetch_linkedin_profile(url: str) -> Dict[str, Any]:
    """Fetch profile data from LinkedIn"""
    try:
        if not api:
            logger.warning("LinkedIn API not initialized")
            return {}
            
        # Extract profile ID from URL
        profile_id = url.split('/in/')[-1].strip('/')
        logger.info(f"Attempting to fetch profile for ID: {profile_id}")
        
        # Fetch profile data
        profile_data = api.get_profile(profile_id)
        logger.info("Successfully fetched profile data")
        
        # Extract profile picture URL
        profile_picture_url = None
        try:
            if 'profilePicture' in profile_data:
                picture_data = profile_data['profilePicture']
                if 'displayImage' in picture_data:
                    profile_picture_url = picture_data['displayImage']
                    logger.info(f"Found profile picture: {profile_picture_url}")
        except Exception as pic_error:
            logger.warning(f"Could not fetch profile picture: {str(pic_error)}")
        
        # Return structured data
        return {
            'full_name': profile_data.get('firstName', '') + ' ' + profile_data.get('lastName', ''),
            'headline': profile_data.get('headline', ''),
            'location': profile_data.get('locationName', ''),
            'current_company': profile_data.get('companyName', ''),
            'summary': profile_data.get('summary', ''),
            'profile_picture_url': profile_picture_url
        }
        
    except Exception as e:
        logger.error(f"Error fetching LinkedIn profile: {str(e)}")
        return {}

async def test_linkedin(update: Update, context: CallbackContext) -> None:
    """Admin command to test LinkedIn API connection"""
    if update.message.from_user.id not in ADMIN_IDS:
        return
        
    try:
        logger.info("Testing LinkedIn API connection...")
        if api is None:
            await update.message.reply_text("LinkedIn API not initialized!")
            return
            
        # Try to fetch a test profile
        test_profile = await asyncio.to_thread(api.get_profile, 'williamhgates')
        if test_profile:
            await update.message.reply_text("LinkedIn API connection successful!")
            logger.info("LinkedIn API test successful")
        else:
            await update.message.reply_text("LinkedIn API connected but returned no data")
            logger.warning("LinkedIn API test returned no data")
            
    except Exception as e:
        error_message = f"LinkedIn API test failed: {str(e)}"
        logger.error(error_message, exc_info=True)
        await update.message.reply_text(f"Error: {error_message}")

async def status(update: Update, context: CallbackContext) -> None:
    """Check bot status"""
    try:
        status_text = (
            "🤖 *Bot Status Report*\n\n"
            f"🟢 Bot Service: *Active*\n"
            f"🗄️ Database: *{'Connected' if engine else 'Disconnected'}*\n"
            f"🔗 LinkedIn API: *{'Connected' if api else 'Disconnected'}*\n\n"
            f"⚡️ Response Time: *Fast*\n"
            f"🔐 Security: *Enabled*\n\n"
            "All systems operational! ✨"
        )
        await update.message.reply_text(status_text, parse_mode='Markdown')
        logger.info(f"Status check by user {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in status command: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "⚠️ *Error checking status*\n"
            "Please try again later.",
            parse_mode='Markdown'
        )

async def format_profile_info(profile_data: dict) -> str:
    """Format profile information into a readable message"""
    sections = []
    
    # Header with name and headline
    header = []
    if profile_data.get('full_name'):
        header.append(f"👤 *{profile_data['full_name']}*")
    if profile_data.get('headline'):
        header.append(f"✨ _{profile_data['headline']}_")
    if header:
        sections.append("\n".join(header))
    
    # Professional Info
    prof_info = []
    if profile_data.get('current_company'):
        prof_info.append(f"🏢 *Current Company:*\n   {profile_data['current_company']}")
    if profile_data.get('location'):
        prof_info.append(f"📍 *Location:*\n   {profile_data['location']}")
    if prof_info:
        sections.append("\n".join(prof_info))
    
    # Summary/About
    if profile_data.get('summary'):
        summary = (f"📝 *About:*\n"
                  f"_{profile_data['summary'][:300]}{'...' if len(profile_data['summary']) > 300 else ''}_")
        sections.append(summary)
    
    # Profile Link
    if profile_data.get('linkedin_url'):
        sections.append(f"🔗 [View Complete LinkedIn Profile]({profile_data['linkedin_url']})")
    
    # Footer
    sections.append("\n━━━━━━━━━━━━━━━━━━━━━")
    
    return "\n\n".join(sections)

async def search_profiles(update: Update, context: CallbackContext) -> None:
    """Search for profiles based on keywords"""
    user_id = update.message.from_user.id
    search_query = ' '.join(context.args).lower()
    
    if not search_query:
        await update.message.reply_text(
            "Please provide search terms.\n"
            "Example: /search software engineer"
        )
        return
        
    try:
        with engine.connect() as conn:
            # Search across multiple fields
            query = select(linkedin_table).where(
                or_(
                    func.lower(linkedin_table.c.full_name).contains(search_query),
                    func.lower(linkedin_table.c.headline).contains(search_query),
                    func.lower(linkedin_table.c.current_company).contains(search_query),
                    func.lower(linkedin_table.c.location).contains(search_query)
                )
            )
            results = conn.execute(query).fetchall()
            
        if not results:
            await update.message.reply_text("No profiles found matching your search.")
            return
            
        response = "🔍 *Search Results:*\n\n"
        for profile in results:
            response += (
                f"👤 *{profile.full_name or 'Name not available'}*\n"
                f"📝 {profile.headline or 'No headline'}\n"
                f"🔗 {profile.linkedin_url}\n\n"
            )
            
        await update.message.reply_text(
            response,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error in search: {str(e)}", exc_info=True)
        await update.message.reply_text("Sorry, an error occurred while searching.")

async def profile_stats(update: Update, context: CallbackContext) -> None:
    """Show profile statistics"""
    try:
        with engine.connect() as conn:
            # Get total profiles
            total = conn.execute(select(func.count()).select_from(linkedin_table)).scalar()
            
            # Get most common companies
            company_query = select(
                linkedin_table.c.current_company,
                func.count(linkedin_table.c.current_company).label('count')
            ).group_by(linkedin_table.c.current_company).order_by(text('count DESC')).limit(3)
            top_companies = conn.execute(company_query).fetchall()
            
            # Get most common locations
            location_query = select(
                linkedin_table.c.location,
                func.count(linkedin_table.c.location).label('count')
            ).group_by(linkedin_table.c.location).order_by(text('count DESC')).limit(3)
            top_locations = conn.execute(location_query).fetchall()
            
        stats_text = (
            "📊 *Network Statistics*\n\n"
            f"👥 Total Profiles: *{total}*\n\n"
            "🏢 *Top Companies:*\n"
        )
        
        for company in top_companies:
            if company.current_company:
                stats_text += f"• {company.current_company}: {company.count}\n"
                
        stats_text += "\n📍 *Top Locations:*\n"
        for location in top_locations:
            if location.location:
                stats_text += f"• {location.location}: {location.count}\n"
                
        await update.message.reply_text(stats_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in profile_stats: {str(e)}", exc_info=True)
        await update.message.reply_text("Sorry, an error occurred while fetching statistics.")

async def export_profiles(update: Update, context: CallbackContext) -> None:
    """Export profiles to CSV"""
    user_id = update.message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("This command is only available to administrators.")
        return
        
    try:
        with engine.connect() as conn:
            profiles = conn.execute(select(linkedin_table)).fetchall()
            
        if not profiles:
            await update.message.reply_text("No profiles to export.")
            return
            
        # Create CSV in memory
        output = BytesIO()
        writer = csv.writer(output)
        writer.writerow(['Full Name', 'LinkedIn URL', 'Headline', 'Company', 'Location'])
        
        for profile in profiles:
            writer.writerow([
                profile.full_name,
                profile.linkedin_url,
                profile.headline,
                profile.current_company,
                profile.location
            ])
            
        output.seek(0)
        await update.message.reply_document(
            document=InputFile(output, filename='linkedin_profiles.csv'),
            caption="Here are all the LinkedIn profiles in CSV format."
        )
        
    except Exception as e:
        logger.error(f"Error in export_profiles: {str(e)}", exc_info=True)
        await update.message.reply_text("Sorry, an error occurred while exporting profiles.")

def is_valid_linkedin_url(url: str) -> bool:
    """Validate LinkedIn URL format"""
    linkedin_pattern = r'^https?:\/\/(www\.)?linkedin\.com\/in\/[\w\-\_\%]+\/?$'
    return bool(re.match(linkedin_pattern, url))

CONNECT_TIMEOUT = 30.0  # seconds
READ_TIMEOUT = 30.0    # seconds

def reset_event_loop():
    """Reset the event loop for Windows platform"""
    if platform.system() == 'Windows':
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except Exception as e:
            logger.error(f"Error resetting event loop: {str(e)}")

async def show_user_list(update: Update, context: CallbackContext, page: int = 0) -> None:
    """Show paginated list of registered users"""
    try:
        USERS_PER_PAGE = 4
        user_id = update.message.from_user.id
        
        with engine.connect() as conn:
            # Get total count and users
            total_count = conn.execute(
                select(func.count()).select_from(linkedin_table)
            ).scalar()
            
            # Get paginated users with all profile information
            query = select(linkedin_table).order_by(
                linkedin_table.c.created_at.desc()
            ).offset(page * USERS_PER_PAGE).limit(USERS_PER_PAGE)
            
            users = conn.execute(query).fetchall()
            
        if not users:
            if page == 0:
                await update.message.reply_text(
                    "No users registered yet! 😊\n"
                    "Be the first one to share your LinkedIn profile!",
                    reply_markup=await get_main_keyboard()
                )
            else:
                await update.message.reply_text(
                    "No more users to show.",
                    reply_markup=await get_main_keyboard()
                )
            return

        # Send profiles one by one
        for user in users:
            try:
                # Create profile card
                profile_text = (
                    f"👤 *{user.full_name or 'Name not available'}*" + "\n" +
                    (f"✨ {user.headline}" + "\n" if hasattr(user, 'headline') and user.headline else "") +
                    (f"🏢 {user.current_company}" + "\n" if hasattr(user, 'current_company') and user.current_company else "") +
                    (f"📍 {user.location}" + "\n" if hasattr(user, 'location') and user.location else "") +
                    (f"📝 {user.summary}" + "\n\n" if hasattr(user, 'summary') and user.summary else "\n") +
                    f"🔗 [View Full Profile]({user.linkedin_url})" + "\n" +
                    ("━" * 30)
                )

                # Only try to access profile_picture_url if it exists
                if hasattr(user, 'profile_picture_url') and user.profile_picture_url:
                    try:
                        await update.message.reply_photo(
                            photo=user.profile_picture_url,
                            caption=profile_text,
                            parse_mode='Markdown'
                        )
                    except Exception as photo_error:
                        logger.error(f"Error sending photo: {str(photo_error)}")
                        await update.message.reply_text(
                            profile_text,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                else:
                    await update.message.reply_text(
                        profile_text,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )

            except Exception as e:
                logger.error(f"Error sending profile: {str(e)}")
                continue

        # Add pagination controls
        total_pages = (total_count + USERS_PER_PAGE - 1) // USERS_PER_PAGE
        
        # Only show pagination if there are multiple pages
        if total_pages > 1:
            keyboard = []
            if page > 0:
                keyboard.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"users_page_{page-1}"))
            if (page + 1) * USERS_PER_PAGE < total_count:
                keyboard.append(InlineKeyboardButton("Next ➡️", callback_data=f"users_page_{page+1}"))
            
            if keyboard:  # Only show pagination controls if there are buttons to show
                pagination_text = f"\nPage {page + 1} of {total_pages}"
                await update.message.reply_text(
                    pagination_text,
                    reply_markup=InlineKeyboardMarkup([keyboard])
                )

    except Exception as e:
        logger.error(f"Error showing user list: {str(e)}", exc_info=True)
        await update.message.reply_text(
            "Sorry, there was an error fetching the user list.",
            reply_markup=await get_main_keyboard()
        )

async def button_callback(update: Update, context: CallbackContext) -> None:
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data.startswith("users_page_"):
            page = int(query.data.split("_")[-1])
            # Create a new update object with the message
            new_update = Update(update.update_id, message=query.message)
            await show_user_list(new_update, context, page)
            
    except Exception as e:
        logger.error(f"Error in button callback: {str(e)}", exc_info=True)
        await query.message.reply_text(
            "Sorry, there was an error processing your request.",
            reply_markup=await get_main_keyboard()
        )

def main():
    logger.info("Starting bot...")
    max_retries = 3
    retry_delay = 5  # seconds
    
    while True:  # Keep the bot running indefinitely
        try:
            # Reset event loop
            reset_event_loop()
            
            # Create new application instance
            application = (
                Application.builder()
                .token(TELEGRAM_BOT_TOKEN)
                .connect_timeout(CONNECT_TIMEOUT)
                .read_timeout(READ_TIMEOUT)
                .get_updates_connect_timeout(CONNECT_TIMEOUT)
                .get_updates_read_timeout(READ_TIMEOUT)
                .build()
            )
            
            # Add handlers
            logger.info("Setting up command handlers...")
            application.add_handler(CommandHandler("start", start))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            application.add_handler(CommandHandler("delete", delete_profile))
            application.add_handler(CommandHandler("update", update_profile))
            application.add_handler(CommandHandler("help", help_command))
            application.add_handler(CommandHandler("test_linkedin", test_linkedin))
            application.add_handler(CommandHandler("status", status))
            application.add_handler(CommandHandler("search", search_profiles))
            application.add_handler(CommandHandler("stats", profile_stats))
            application.add_handler(CommandHandler("export", export_profiles))
            application.add_handler(CallbackQueryHandler(button_callback))
            application.add_error_handler(error_handler)
            
            logger.info("Bot is ready to start polling")
            
            # Run the bot with proper shutdown handling
            application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
                stop_signals=None  # Disable signal handling
            )
            
        except telegram.error.NetworkError as e:
            logger.error(f"Network error occurred: {str(e)}")
            time.sleep(retry_delay)
            continue
            
        except telegram.error.TimedOut:
            logger.warning(f"Connection timed out. Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
            continue
            
        except telegram.error.Conflict as e:
            logger.error(f"Conflict error: {str(e)}")
            time.sleep(retry_delay * 2)  # Wait longer for conflicts
            continue
            
        except Exception as e:
            logger.error("Failed to start bot:", exc_info=True)
            time.sleep(retry_delay)
            continue

if __name__ == '__main__':
    try:
        # Add constants at the top of the file
        CONNECT_TIMEOUT = 30.0  # seconds
        READ_TIMEOUT = 30.0    # seconds
        
        # Start the bot
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error("Fatal error occurred:", exc_info=True)

logger.info("Checking environment variables...")
env_vars = {
    'TELEGRAM_BOT_TOKEN': bool(TELEGRAM_BOT_TOKEN),
    'DB_HOST': bool(DB_HOST),
    'DB_PORT': bool(DB_PORT),
    'DB_NAME': bool(DB_NAME),
    'DB_USER': bool(DB_USER),
    'DB_PASSWORD': bool(DB_PASSWORD),
    'LINKEDIN_USERNAME': bool(os.getenv('LINKEDIN_USERNAME')),
    'LINKEDIN_PASSWORD': bool(os.getenv('LINKEDIN_PASSWORD'))
}
logger.info(f"Environment variables loaded: {env_vars}")
