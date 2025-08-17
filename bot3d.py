import logging
import asyncio
import io
import psycopg2
import os
from typing import Dict, List, Tuple, Optional

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    MessageHandler, filters, CallbackQueryHandler
)

# Configuration from environment variables
TOKEN = os.getenv('BOT_TOKEN')
MAX_CARDS_PER_SESSION = 50
CHECK_DELAY = 1.5

# Admin user IDs from environment variable (comma-separated)
ADMIN_USER_IDS_STR = os.getenv('ADMIN_USER_IDS', '5895491379')
try:
    ADMIN_USER_IDS = [int(user_id.strip()) for user_id in ADMIN_USER_IDS_STR.split(',') if user_id.strip()]
except:
    ADMIN_USER_IDS = [5895491379]  # Fallback

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global user data storage
user_data: Dict[int, Dict] = {}

def get_db_connection():
    """Get PostgreSQL database connection"""
    try:
        database_url = (
            os.getenv('DATABASE_URL') or 
            os.getenv('DATABASE_PRIVATE_URL') or
            os.getenv('DATABASE_PUBLIC_URL')
        )
        
        if database_url:
            if database_url.startswith('postgres://'):
                database_url = database_url.replace('postgres://', 'postgresql://', 1)
            
            return psycopg2.connect(database_url)
        else:
            host = os.getenv('PGHOST') or os.getenv('DB_HOST', 'localhost')
            port = os.getenv('PGPORT') or os.getenv('DB_PORT', '5432')
            database = os.getenv('PGDATABASE') or os.getenv('DB_NAME', 'railway')
            user = os.getenv('PGUSER') or os.getenv('DB_USER', 'postgres')
            password = os.getenv('PGPASSWORD') or os.getenv('DB_PASSWORD', '')
            
            return psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password
            )
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def init_db():
    """Initialize the PostgreSQL database for subscriptions."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

def add_subscriber_to_db(user_id: int, username: str, first_name: str) -> bool:
    """Add a user to the subscribers table."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscribers (user_id, username, first_name, is_active) 
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                is_active = TRUE,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, username, first_name))
        conn.commit()
        affected_rows = cursor.rowcount
        cursor.close()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        logger.error(f"Error adding subscriber {user_id} to DB: {e}")
        return False

def remove_subscriber_from_db(user_id: int) -> bool:
    """Remove a user from the subscribers table (set is_active to FALSE)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE subscribers 
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP 
            WHERE user_id = %s
        """, (user_id,))
        conn.commit()
        affected_rows = cursor.rowcount
        cursor.close()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        logger.error(f"Error removing subscriber {user_id} from DB: {e}")
        return False

def activate_subscriber_in_db(user_id: int) -> bool:
    """Activate a user in the subscribers table (set is_active to TRUE)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE subscribers 
            SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP 
            WHERE user_id = %s
        """, (user_id,))
        conn.commit()
        affected_rows = cursor.rowcount
        cursor.close()
        conn.close()
        return affected_rows > 0
    except Exception as e:
        logger.error(f"Error activating subscriber {user_id} in DB: {e}")
        return False

def is_user_subscribed(user_id: int) -> bool:
    """Check if a user is an active subscriber."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM subscribers WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result is not None and result[0] is True
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id}: {e}")
        return False

def get_all_subscribers() -> List[Tuple[int, str, str, bool]]:
    """Get all subscribers from the database."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, first_name, is_active FROM subscribers ORDER BY created_at DESC")
        subscribers = cursor.fetchall()
        cursor.close()
        conn.close()
        return subscribers
    except Exception as e:
        logger.error(f"Error getting subscribers: {e}")
        return []


class CardChecker:
    """Handles card checking logic"""
    
    def __init__(self):
        self.cookies = {
            '.AspNetCore.Antiforgery.ct0OCrh2AQg': 'CfDJ8BEkQ_pLnxxMoeoVdDo1mqfAjUWrV7x-otIGacRXJZlfNAtDRtbPqWyCSSVPB-M0ksvBWng7a7nqay-sQT4rd2NJRQPiMLzUMd16BNnuh5iM4WliAkOsq9JUq10w0rVuR-B3u7aUfLU66N06D9Zlzo',
            'SERVERID': 'srv3_d9ef_136|aJsqV|aJsqH',
        }
        
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded',
            'DNT': '1',
            'Origin': 'https://ecommerce.its-connect.com',
            'Referer': 'https://ecommerce.its-connect.com/PayPage/CEF',
            'Sec-Fetch-Dest': 'iframe',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Storage-Access': 'active',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        }
    
    async def check_card(self, card: str) -> Tuple[Optional[bool], str]:
        """Check a single card"""
        try:
            card_parts = card.strip().split("|")
            if len(card_parts) != 4:
                return None, f"Invalid format: {card}"
            
            number, month, year, cvv = card_parts
            
            if len(year) == 4:
                year = year[-2:]
            
            data = {
                'DigitalWalletToken': '',
                'DigitalWallet': '',
                'CardNumber': number,
                'ExpiryMonth': month,
                'ExpiryYear': year,
                'CardHolderName': cvv,
                'CVV': cvv,
                'PageSessionId': '6kKqDaerAMCo7o88E2DnsjJlvO5',
                'ITSBrowserScreenHeight': '786',
                'ITSBrowserScreenWidth': '1397',
                'ITSBrowserScreenColorDepth': '24',
                'ITSBrowserTimeZoneOffset': '-180',
                'ITSBrowserHasJavaScript': 'true',
                'ITSBrowserHasJava': 'false',
                'ITSBrowserLanguage': 'en',
                '__RequestVerificationToken': 'CfDJ8BEkQ_pLnxxMoeoVdDo1mqf1YXYyijrfbV7QR8ut_XmcP5ujman4W6QH3JcSmorRBPLmd2PvzRvW-9Zn-X__dQnWRdlTPWDtyHeoG-XCrLV2X6RU5gI5dasMudnyOeqLNDKFaeXRyF-wz1sAP6oSsg4',
            }

            response = requests.post(
                'https://ecommerce.its-connect.com/PayPage/Submit/6kKqDaerAMCo7o88E2DnsjJlvO5',
                cookies=self.cookies,
                headers=self.headers,
                data=data,
                timeout=20
            )
            
            response_text = response.text.lower()
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string.strip().lower() if soup.title else ""

            if "acs authentication redirect page" in title or "acs authentication redirect page" in response_text:
                return True, card
            else:
                return False, card
                
        except Exception as e:
            logger.error(f"Error checking card {card}: {e}")
            return None, f"Error on {card}: {e}"


class UserSession:
    """Manages user session data"""
    
    def __init__(self):
        self.cards: List[str] = []
        self.approved: List[str] = []
        self.rejected: List[str] = []
        self.errors: List[str] = []
        self.paused: bool = False
        self.current_index: int = 0
        self.status_message_id: Optional[int] = None
        self.state: str = "menu"
        self.current_rejected_index: int = 0
    
    def reset(self):
        """Reset session data"""
        self.__init__()
    
    @property
    def total_cards(self) -> int:
        return len(self.cards)


class TelegramBot:
    """Main bot class"""
    
    def __init__(self):
        self.card_checker = CardChecker()
    
    def get_or_create_session(self, chat_id: int) -> UserSession:
        """Get or create user session"""
        if chat_id not in user_data:
            user_data[chat_id] = UserSession()
        return user_data[chat_id]

    def is_admin(self, user_id: int) -> bool:
        """Check if the user is an admin."""
        return user_id in ADMIN_USER_IDS
    
    def get_main_menu_keyboard(self, session: UserSession = None, is_admin_user: bool = False) -> InlineKeyboardMarkup:
        """Main menu keyboard"""
        keyboard = [
            [InlineKeyboardButton("📝 Add Cards", callback_data="add_cards")],
        ]
        
        if session and session.cards and session.current_index < len(session.cards):
            keyboard.append([InlineKeyboardButton("▶️ Start Checking", callback_data="start_check")])
        elif session and session.cards and session.current_index >= len(session.cards):
            keyboard.append([InlineKeyboardButton("✅ Checking Complete", callback_data="view_results")])
        
        keyboard.extend([
            [InlineKeyboardButton("📊 View Results", callback_data="view_results")],
            [InlineKeyboardButton("📥 Download Files", callback_data="download")],
            [InlineKeyboardButton("🔄 Reset Session", callback_data="reset")]
        ])

        if is_admin_user:
            keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])

        return InlineKeyboardMarkup(keyboard)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        username = update.effective_user.username or "N/A"
        first_name = update.effective_user.first_name or "N/A"

        # Add user to DB
        add_subscriber_to_db(user_id, username, first_name)

        # Check if admin
        if self.is_admin(user_id):
            # Auto-activate admin
            activate_subscriber_in_db(user_id)

        if not is_user_subscribed(user_id):
            await update.message.reply_text(
                "🔒 *Access Denied*\"You are not subscribed to use this bot. Please contact the administrator to gain access.",
                parse_mode="Markdown"
            )
            return

        session = self.get_or_create_session(chat_id)
        session.reset()
        session.state = "menu"
        
        welcome_text = (
            "🚀 *Welcome to Card Checker Bot!*\n\n"
            "This bot will help you check credit cards.\n"
            f"Maximum {MAX_CARDS_PER_SESSION} cards per session.\n\n"
            "*Card Format:* `Number|MM|YYYY|CVV`\n"
            "*Example:* `4532123456789012|12|2025|123`"
        )
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode="Markdown",
            reply_markup=self.get_main_menu_keyboard(session, self.is_admin(user_id))
        )

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all button callbacks"""
        query = update.callback_query
        await query.answer()
        
        chat_id = query.message.chat.id
        user_id = query.from_user.id
        message_id = query.message.message_id
        session = self.get_or_create_session(chat_id)

        if not is_user_subscribed(user_id) and not query.data.startswith("admin_"):
            await query.edit_message_text(
                "🔒 *Access Denied*\n\n"
                "You are not subscribed to use this bot. Please contact the administrator to gain access.",
                parse_mode="Markdown"
            )
            return
        
        if query.data == "admin_panel":
            if not self.is_admin(user_id):
                await query.edit_message_text("🚫 *Access Denied*\nYou are not authorized to access the admin panel.", parse_mode="Markdown")
                return
            session.state = "admin_menu"
            await query.edit_message_text(
                "⚙️ *Admin Panel*\n\nChoose an action:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add Subscriber", callback_data="admin_add_sub")],
                    [InlineKeyboardButton("➖ Remove Subscriber", callback_data="admin_remove_sub")],
                    [InlineKeyboardButton("🔄 Activate Subscriber", callback_data="admin_activate_sub")],
                    [InlineKeyboardButton("📋 List Subscribers", callback_data="admin_list_sub")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )
        
        elif query.data == "admin_add_sub":
            if not self.is_admin(user_id): return
            session.state = "admin_add_sub_waiting_id"
            await query.edit_message_text(
                "➕ *Add Subscriber*\n\nPlease send the *User ID* of the user you want to add.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_panel")]])
            )
        
        elif query.data == "admin_remove_sub":
            if not self.is_admin(user_id): return
            session.state = "admin_remove_sub_waiting_id"
            await query.edit_message_text(
                "➖ *Remove Subscriber*\n\nPlease send the *User ID* of the user you want to remove.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_panel")]])
            )

        elif query.data == "admin_activate_sub":
            if not self.is_admin(user_id): return
            session.state = "admin_activate_sub_waiting_id"
            await query.edit_message_text(
                "🔄 *Activate Subscriber*\n\nPlease send the *User ID* of the user you want to activate.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_panel")]])
            )

        elif query.data == "admin_list_sub":
            if not self.is_admin(user_id): return
            subscribers = get_all_subscribers()
            if not subscribers:
                text = "📋 *No Subscribers Found.*"
            else:
                text = "📋 *Subscribers List:*\n\n"
                for sub_id, sub_username, sub_first_name, is_active in subscribers:
                    status = "✅ Active" if is_active else "❌ Inactive"
                    text += f"ID: `{sub_id}`\n" \
                            f"Name: {sub_first_name} (@{sub_username if sub_username != 'N/A' else 'N/A'})\n" \
                            f"Status: {status}\n\n"
            
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Admin Panel", callback_data="admin_panel")]])
            )

        elif query.data == "main_menu":
            session.state = "menu"
            await self.send_main_menu(context, chat_id, message_id)
        
        elif query.data == "add_cards":
            session.state = "adding_cards"
            text = (
                "📝 *Add Cards*\n\n"
                f"Current cards: *{session.total_cards}*\n"
                f"Remaining slots: *{MAX_CARDS_PER_SESSION - session.total_cards}*\n\n"
                "Send cards in this format (one per line):\n"
                "`4532123456789012|12|2025|123`"
            )
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )

    async def send_main_menu(self, context: ContextTypes.DEFAULT_TYPE, 
                           chat_id: int, message_id: int = None):
        """Send main menu"""
        session = self.get_or_create_session(chat_id)
        is_admin_user = self.is_admin(chat_id)
        
        text = (
            f"🤖 *Card Checker Bot*\n\n"
            f"📊 *Session Status:*\n"
            f"Cards Added: *{session.total_cards}*\n"
            f"Approved: *{len(session.approved)}* ✅\n"
            f"Rejected: *{len(session.rejected)}* ❌\n"
            f"Errors: *{len(session.errors)}* ⚠️\n\n"
            f"Choose an option:"
        )
        
        try:
            if message_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=self.get_main_menu_keyboard(session, is_admin_user)
                )
            else:
                await context.bot.send_message(
                    chat_id,
                    text,
                    parse_mode="Markdown",
                    reply_markup=self.get_main_menu_keyboard(session, is_admin_user)
                )
        except Exception as e:
            logger.error(f"Error sending main menu: {e}")

    async def admin_message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages specifically for admin actions."""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        session = self.get_or_create_session(chat_id)

        if session.state == "admin_add_sub_waiting_id":
            if not self.is_admin(user_id): return
            try:
                target_user_id = int(update.message.text.strip())
                if add_subscriber_to_db(target_user_id, "N/A", "N/A"):
                    await update.message.reply_text(f"✅ User `{target_user_id}` added/activated as subscriber.", parse_mode="Markdown")
                else:
                    await update.message.reply_text(f"ℹ️ User `{target_user_id}` was already an active subscriber.", parse_mode="Markdown")
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID. Please send a valid integer ID.", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ An error occurred: {e}", parse_mode="Markdown")
            finally:
                session.state = "admin_menu"

        elif session.state == "admin_remove_sub_waiting_id":
            if not self.is_admin(user_id): return
            try:
                target_user_id = int(update.message.text.strip())
                if remove_subscriber_from_db(target_user_id):
                    await update.message.reply_text(f"✅ User `{target_user_id}` removed (deactivated) from subscribers.", parse_mode="Markdown")
                else:
                    await update.message.reply_text(f"ℹ️ User `{target_user_id}` not found or already inactive.", parse_mode="Markdown")
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID. Please send a valid integer ID.", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ An error occurred: {e}", parse_mode="Markdown")
            finally:
                session.state = "admin_menu"

        elif session.state == "admin_activate_sub_waiting_id":
            if not self.is_admin(user_id): return
            try:
                target_user_id = int(update.message.text.strip())
                if activate_subscriber_in_db(target_user_id):
                    await update.message.reply_text(f"✅ User `{target_user_id}` activated as subscriber.", parse_mode="Markdown")
                else:
                    await update.message.reply_text(f"ℹ️ User `{target_user_id}` not found or already active.", parse_mode="Markdown")
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID. Please send a valid integer ID.", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ An error occurred: {e}", parse_mode="Markdown")
            finally:
                session.state = "admin_menu"

        elif session.state == "adding_cards":
            if not is_user_subscribed(user_id):
                await update.message.reply_text(
                    "🔒 *Access Denied*\n\n"
                    "You are not subscribed to use this bot.",
                    parse_mode="Markdown"
                )
                return

            new_cards = [card.strip() for card in update.message.text.strip().split("\n") if card.strip()]
            
            current_len = len(session.cards)
            allowed = MAX_CARDS_PER_SESSION - current_len
            to_add = new_cards[:allowed]
            session.cards.extend(to_add)
            
            response_text = f"✅ Added {len(to_add)} cards\nTotal: {len(session.cards)} cards"
            
            if len(new_cards) > allowed:
                response_text += f"\n⚠️ Max {MAX_CARDS_PER_SESSION} cards allowed. Extra ignored."
            
            await update.message.reply_text(
                response_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add More Cards", callback_data="add_cards")],
                    [InlineKeyboardButton("✅ Done Adding", callback_data="main_menu")]
                ])
            )


def main():
    """Main function"""
    logger.info("Starting Card Checker Bot...")
    
    if not TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return
    
    try:
        init_db()
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return
    
    bot = TelegramBot()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CallbackQueryHandler(bot.callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.admin_message_handler))
    
    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
