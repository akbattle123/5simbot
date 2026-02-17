import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import requests
import sqlite3
from functools import wraps

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_KEY_5SIM = os.getenv("API_KEY_5SIM")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database Setup
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        wallet_balance REAL DEFAULT 0,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        service TEXT,
        country TEXT,
        phone_number TEXT,
        status TEXT,
        expiry_time TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        txn_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        type TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        screenshot_url TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS services (
        service_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        base_price REAL,
        markup REAL,
        enabled INTEGER DEFAULT 1
    )''')
    conn.commit()
    conn.close()

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("❌ Sirf Admin!")
            return
        return await func(update, context)
    return wrapper

class BotDatabase:
    @staticmethod
    def get_connection():
        return sqlite3.connect('bot_data.db')
    
    @staticmethod
    def get_user_balance(user_id):
        conn = BotDatabase.get_connection()
        c = conn.cursor()
        c.execute('SELECT wallet_balance FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 0

    @staticmethod
    def add_user(user_id, username):
        conn = BotDatabase.get_connection()
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
        conn.commit()
        conn.close()

    @staticmethod
    def update_balance(user_id, amount):
        conn = BotDatabase.get_connection()
        c = conn.cursor()
        c.execute('UPDATE users SET wallet_balance = wallet_balance + ? WHERE user_id = ?', (amount, user_id))
        conn.commit()
        conn.close()

# 5sim API Functions
def get_5sim_services():
    headers = {"Authorization": f"Bearer {API_KEY_5SIM}"}
    try:
        response = requests.get('https://5sim.net/v1/services', headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get('services', {})
        return {}
    except Exception as e:
        logger.error(f"5sim API error: {e}")
        return {}

def get_5sim_countries(service):
    headers = {"Authorization": f"Bearer {API_KEY_5SIM}"}
    try:
        response = requests.get(f'https://5sim.net/v1/countries/{service}', headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get('countries', {})
        return {}
    except Exception as e:
        logger.error(f"5sim countries error: {e}")
        return {}

def buy_number_5sim(service, country, operator='any'):
    headers = {"Authorization": f"Bearer {API_KEY_5SIM}"}
    payload = {"service": service, "country": country, "operator": operator}
    try:
        response = requests.post('https://5sim.net/v1/user/buy/activation', json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Buy number error: {e}")
        return None

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    BotDatabase.add_user(user.id, user.username or "Anonymous")
    
    keyboard = [
        [InlineKeyboardButton("📜 Terms & Conditions", callback_data="terms")],
        [InlineKeyboardButton("🎫 Support Ticket", callback_data="support")],
        [InlineKeyboardButton("🚀 Start", callback_data="home")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎉 *Virtual Number Selling Bot* 🎉\n\n"
        "Welcome! Yahan se aap virtual numbers buy kar sakte ho.\n"
        "Shukriya!",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🏦 Balance", callback_data="balance")],
        [InlineKeyboardButton("📱 Buy Number", callback_data="buy_service")],
        [InlineKeyboardButton("📂 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton("🌍 Services", callback_data="services")],
        [InlineKeyboardButton("🎫 Support", callback_data="support")],
        [InlineKeyboardButton("🎁 Referral", callback_data="referral")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🏠 *Home Screen*\n\nKya karna chahte ho?",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    balance = BotDatabase.get_user_balance(user_id)
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Balance", callback_data="add_balance")],
        [InlineKeyboardButton("🔙 Back", callback_data="home")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"💰 *Your Balance*\n\nBalance: *${balance:.2f}*",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def buy_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    services = get_5sim_services()
    keyboard = []
    
    for service_name in list(services.keys())[:8]:
        keyboard.append([InlineKeyboardButton(service_name, callback_data=f"select_country_{service_name}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="home")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📱 *Select Service*",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📂 *My Orders*\n\n(Orders feature coming soon!)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home")]])
    )

async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Dashboard", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Wallets", callback_data="admin_wallets")],
        [InlineKeyboardButton("🛠 Services", callback_data="admin_services")],
        [InlineKeyboardButton("📜 Logs", callback_data="admin_logs")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👑 *Admin Panel*",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "home":
        await home(update, context)
    elif data == "balance":
        await balance(update, context)
    elif data == "buy_service":
        await buy_service(update, context)
    elif data == "my_orders":
        await my_orders(update, context)
    elif data == "admin_dashboard":
        await admin_dashboard(update, context)

def main():
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_dashboard))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    app.run_polling()

if __name__ == "__main__":
    main()