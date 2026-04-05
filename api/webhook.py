import os
import json
import time
import random
import datetime
import logging
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
from flask import Flask, request

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ═══════════════════════════════════════════════════════════════════════════
#                           CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8369175102:AAGo7zQTsL475JcTje6vTCsnn3il79HxS1Y")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6188878248"))
BOT_VERSION = "2.0.0"

# ═══════════════════════════════════════════════════════════════════════════
#                        CONVERSATION STATES
# ═══════════════════════════════════════════════════════════════════════════
class States:
    IDLE = 0
    ENTER_GMAIL = 1
    ENTER_PASSWORD = 2
    SELECT_METHOD = 3
    ENTER_AMOUNT = 4
    ENTER_ACCOUNT = 5

S = States

# ═══════════════════════════════════════════════════════════════════════════
#                   VERCEL COMPATIBLE ADVANCED DATABASE
# ═══════════════════════════════════════════════════════════════════════════
class VercelDatabase:
    """Vercel Serverless এর জন্য In-Memory Database"""
    def __init__(self):
        self.users: Dict[int, dict] = {}
        self.pending_gmails: Dict[int, dict] = {}
        self.pending_withdrawals: List[dict] = []
        self.settings = {
            'gmail_price': 5.0,
            'min_withdraw': 100.0,
            'referral_bonus': 2.0,
            'daily_bonus': 1.0,
            'welcome_bonus': 5.0
        }

    def get_user(self, user_id: int) -> Optional[dict]:
        return self.users.get(user_id)

    def get_or_create_user(self, user_id: int, username: str, first_name: str) -> dict:
        if user_id not in self.users:
            self.users[user_id] = {
                'user_id': user_id, 'username': username, 'first_name': first_name,
                'balance': float(self.settings['welcome_bonus']), 'frozen_balance': 0,
                'total_earned': float(self.settings['welcome_bonus']), 'total_withdrawn': 0,
                'gmail_count': 0, 'is_banned': False, 'join_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        else:
            self.users[user_id]['username'] = username
            self.users[user_id]['first_name'] = first_name
        return self.users[user_id]

    def is_admin(self, user_id: int) -> bool:
        return user_id == ADMIN_ID

    def get_balance(self, user_id: int) -> float:
        user = self.get_user(user_id)
        return user['balance'] if user else 0.0

    def add_balance(self, user_id: int, amount: float, desc: str) -> bool:
        if user_id in self.users:
            self.users[user_id]['balance'] += amount
            if amount > 0:
                self.users[user_id]['total_earned'] += amount
            return True
        return False

    def deduct_balance(self, user_id: int, amount: float) -> bool:
        if user_id in self.users and self.users[user_id]['balance'] >= amount:
            self.users[user_id]['balance'] -= amount
            return True
        return False

    def add_pending_gmail(self, user_id: int, email: str, password: str) -> bool:
        self.pending_gmails[user_id] = {'email': email, 'password': password, 'time': time.time()}
        return True

    def get_pending_gmails(self) -> List[dict]:
        return [{'user_id': uid, **data} for uid, data in self.pending_gmails.items()]

    def approve_pending_gmail(self, user_id: int) -> bool:
        if user_id in self.pending_gmails:
            price = self.settings['gmail_price']
            self.add_balance(user_id, price, 'Gmail Approved')
            self.users[user_id]['gmail_count'] += 1
            del self.pending_gmails[user_id]
            return True
        return False

    def add_pending_withdraw(self, user_id: int, amount: float, method: str, account: str) -> bool:
        if self.deduct_balance(user_id, amount):
            self.pending_withdrawals.append({
                'user_id': user_id, 'amount': amount, 'method': method, 'account': account, 'time': time.time(), 'status': 'pending'
            })
            return True
        return False

    def get_overall_stats(self) -> Dict:
        return {
            'total_users': len(self.users),
            'pending_gmails': len(self.pending_gmails),
            'pending_withdrawals': len([w for w in self.pending_withdrawals if w['status'] == 'pending']),
            'total_balance': sum(u['balance'] for u in self.users.values())
        }

# ═══════════════════════════════════════════════════════════════════════════
#                        PREMIUM UI BUILDER
# ═══════════════════════════════════════════════════════════════════════════
class UI:
    @staticmethod
    def header(title: str) -> str:
        return f"╔══════════════════════════╗\n║  <b>{title}</b>\n╚══════════════════════════╝"
    
    @staticmethod
    def row(icon: str, text: str) -> str:
        return f"  {icon} {text}"
    
    @staticmethod
    def divider() -> str:
        return "━━━━━━━━━━━━━━━━━━━━━━"

db = VercelDatabase()

# ═══════════════════════════════════════════════════════════════════════════
#                           FLASK & BOT SETUP
# ═══════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
bot_app = Application.builder().token(BOT_TOKEN).build()

# ═══════════════════════════════════════════════════════════════════════════
#                        BOT HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username, user.first_name)
    
    text = f"""{UI.header("GMAIL SELL BOT V2")}
    
{UI.row("👤", f"নাম: <code>{user.first_name}</code>")}
{UI.row("🪪", f"আইডি: <code>{user.id}</code>")}
{UI.divider()}
{UI.row("💰", f"ব্যালেন্স: <b>{db.get_balance(user.id):.2f} টাকা</b>")}
{UI.row("📧", f"সম্পূর্ণ জমা: <b>{db.get_user(user.id)['gmail_count']}</b>")}
    
<i>📧 জিমেইল জমা দিতে নিচের বাটনে ক্লিক করুন। প্রতিটি ভ্যালিড জিমেইলের জন্য আপনি পাবেন <b>{db.settings['gmail_price']} টাকা</b>।</i>"""
    
    keyboard = [
        [InlineKeyboardButton("📧 জিমেইল জমা দিন", callback_data="submit_gmail")],
        [InlineKeyboardButton("💰 ব্যালেন্স দেখুন", callback_data="balance"), InlineKeyboardButton("💸 উত্তোলন", callback_data="withdraw")],
        [InlineKeyboardButton("📊 আমার পরিসংখ্যান", callback_data="stats"), InlineKeyboardButton("🆘 সাহায্য", callback_data="help")]
    ]
    
    if db.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🛡️ অ্যাডমিন প্যানেল", callback_data="admin_panel")])
        
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data
    
    if data == "submit_gmail":
        context.user_data['state'] = S.ENTER_GMAIL
        await query.edit_message_text("📧 <b>জিমেইল জমা দিন</b>\n\nনিচে জিমেইল আইডি পাঠান (যেমন: example@gmail.com):\n\n/Cancel লিখে বাতিল করুন।", parse_mode="HTML")
        
    elif data == "balance":
        bal = db.get_balance(user.id)
        await query.edit_message_text(f"{UI.header('ব্যালেন্স')}\n\n{UI.row('💰', f'বর্তমান ব্যালেন্স: <b>{bal:.2f} টাকা</b>')}", parse_mode="HTML")
        
    elif data == "withdraw":
        context.user_data['state'] = S.ENTER_AMOUNT
        await query.edit_message_text(f"💸 <b>ব্যালেন্স উত্তোলন</b>\n\n{UI.row('💰', f'আপনার ব্যালেন্স: <b>{db.get_balance(user.id):.2f} টাকা</b>')}\n{UI.row('⚠️', f'ন্যূনতম উত্তোলন: <b>{db.settings['min_withdraw']} টাকা</b>')}\n\nউত্তোলনের পরিমাণ লিখে পাঠান:", parse_mode="HTML")
        
    elif data == "stats":
        u_data = db.get_user(user.id)
        text = f"""{UI.header('পরিসংখ্যান')}
        
{UI.row('💰', f'মোট আয়: <b>{u_data["total_earned"]:.2f} টাকা</b>')}
{UI.row('💸', f'মোট উত্তোলন: <b>{u_data["total_withdrawn"]:.2f} টাকা</b>')}
{UI.row('📧', f'বিক্রিত জিমেইল: <b>{u_data["gmail_count"]}টি</b>')}
{UI.row('📅', f'যোগদান: <code>{u_data["join_date"]}</code>')}"""
        await query.edit_message_text(text, parse_mode="HTML")
        
    elif data == "help":
        text = f"""{UI.header('সাহায্য মেনু')}
        
1. <b>জিমেইল জমা:</b> জিমেইল আইডি ও পাসওয়ার্ড দিন, রিভিউ হলে {db.settings['gmail_price']}টাকা পাবেন।
2. <b>উত্তোলন:</b> {db.settings['min_withdraw']}টাকা থাকলে bKash/Nagad এ উত্তোলন করুন।
3. <b>নিয়ম:</b> ফেক বা ভুয়া জিমেইল দিলে ব্যান হতে পারেন।"""
        await query.edit_message_text(text, parse_mode="HTML")
        
    # ADMIN PANEL LOGICS
    elif data == "admin_panel" and db.is_admin(user.id):
        stats = db.get_overall_stats()
        text = f"""{UI.header('🛡️ অ্যাডমিন প্যানেল')}
        
{UI.row('👥', f'মোট ইউজার: <b>{stats["total_users"]}জন</b>')}
{UI.row('📧', f'পেন্ডিং জিমেইল: <b>{stats["pending_gmails"]}টি</b>')}
{UI.row('💸', f'পেন্ডিং উত্তোলন: <b>{stats["pending_withdrawals"]}টি</b>')}
{UI.row('💰', f'মোট ব্যালেন্স লোড: <b>{stats["total_balance"]:.2f}টাকা</b>')}"""
        
        keyboard = [
            [InlineKeyboardButton("📧 পেন্ডিং জিমেইল", callback_data="admin_pending_gmails"),
             InlineKeyboardButton("💸 পেন্ডিং উত্তোলন", callback_data="admin_pending_withdraws")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    elif data == "admin_pending_gmails" and db.is_admin(user.id):
        pending = db.get_pending_gmails()
        if not pending:
            await query.edit_message_text("✅ কোনো পেন্ডিং জিমেইল নেই।", parse_mode="HTML")
            return
            
        text = f"{UI.header('পেন্ডিং জিমেইল')}\n\n"
        for i, g in enumerate(pending[:5]):
            text += f"<b>{i+1}.</b> <code>{g['email']}</code> [ID: <code>{g['user_id']}</code>]\n"
        
        keyboard = [[InlineKeyboardButton("🔙 ফিরে যান", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    elif data.startswith("approve_") and db.is_admin(user.id):
        target_id = int(data.split("_")[1])
        if db.approve_pending_gmail(target_id):
            await query.answer("✅ জিমেইল অ্যাপ্রুভ করা হয়েছে এবং ব্যালেন্স যোগ হয়েছে!", show_alert=True)
        else:
            await query.answer("❌ জিমেইল পাওয়া যায়নি!", show_alert=True)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = context.user_data.get('state', S.IDLE)
    text = update.message.text
    
    if text.lower() == '/cancel':
        context.user_data['state'] = S.IDLE
        await update.message.reply_text("❌ প্রক্রিয়া বাতিল হয়েছে। /start চাপুন।")
        return

    if state == S.ENTER_GMAIL:
        if "@" not in text or "gmail.com" not in text:
            await update.message.reply_text("⚠️ এটি ভ্যালিড জিমেইল আইডি নয়। আবার লিখুন:")
            return
        context.user_data['temp_email'] = text
        context.user_data['state'] = S.ENTER_PASSWORD
        await update.message.reply_text("🔐 এখন জিমেইলের <b>পাসওয়ার্ড</b> পাঠান:", parse_mode="HTML")
        
    elif state == S.ENTER_PASSWORD:
        email = context.user_data.get('temp_email')
        db.add_pending_gmail(user.id, email, text)
        context.user_data['state'] = S.IDLE
        await update.message.reply_text(f"✅ <b>সফলভাবে জমা হয়েছে!</b>\n\nজিমেইল: <code>{email}</code>\nঅ্যাডমিন রিভিউ করলে {db.settings['gmail_price']} টাকা ব্যালেন্সে যোগ হবে।", parse_mode="HTML")
        
    elif state == S.ENTER_AMOUNT:
        try:
            amount = float(text)
            if amount < db.settings['min_withdraw']:
                await update.message.reply_text(f"⚠️ ন্যূনতম উত্তোলন {db.settings['min_withdraw']} টাকা। আবার লিখুন:")
                return
            if amount > db.get_balance(user.id):
                await update.message.reply_text("❌ আপনার পর্যাপ্ত ব্যালেন্স নেই।")
                context.user_data['state'] = S.IDLE
                return
                
            context.user_data['temp_amount'] = amount
            context.user_data['state'] = S.ENTER_ACCOUNT
            keyboard = [
                [InlineKeyboardButton("bKash", callback_data="method_bKash"), InlineKeyboardButton("Nagad", callback_data="method_Nagad")]
            ]
            await update.message.reply_text("💳 উত্তোলনের মাধ্যম নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        except ValueError:
            await update.message.reply_text("⚠️ শুধুমাত্র সংখ্যা লিখুন (যেমন: 500)")
            
    elif state == S.ENTER_ACCOUNT:
        method = context.user_data.get('temp_method', 'Unknown')
        amount = context.user_data.get('temp_amount')
        
        if db.add_pending_withdraw(user.id, amount, method, text):
            context.user_data['state'] = S.IDLE
            await update.message.reply_text(f"✅ <b>উত্তোলনের আবেদন সফল!</b>\n\n{UI.row('💸', f'পরিমাণ: {amount} টাকা')}\n{UI.row('💳', f'মাধ্যম: {method}')}\n{UI.row('📱', f'নম্বর: {text}')}\n\n@admin অ্যাডমিন শীঘ্রই পেমেন্ট দেবে।", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ উত্তোলন ব্যর্থ হয়েছে।")

async def method_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("method_"):
        context.user_data['temp_method'] = query.data.replace("method_", "")
        await query.edit_message_text("📱 এখন আপনার bKash/Nagad নম্বর লিখে পাঠান (যেমন: 01XXXXXXXXX):")

# ═══════════════════════════════════════════════════════════════════════════
#                           REGISTER HANDLERS
# ═══════════════════════════════════════════════════════════════════════════
bot_app.add_handler(CommandHandler("start", start_cmd))
bot_app.add_handler(CallbackQueryHandler(method_selector, pattern=r"^method_"))
bot_app.add_handler(CallbackQueryHandler(button_callback))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

# ═══════════════════════════════════════════════════════════════════════════
#                           VERCEL WEBHOOK ROUTE
# ═══════════════════════════════════════════════════════════════════════════
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(), bot_app.bot)
        bot_app.create_task(bot_app.process_update(update))
        return "OK", 200
    return "Method Not Allowed", 405

from vercel_wsgi import handle_wsgi
handler = handle_wsgi(app)
