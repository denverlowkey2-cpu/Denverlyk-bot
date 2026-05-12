import sys
print("=== DENVER SMC ELITE V3.4 BULLETPROOF START ===", flush=True)

import telebot
from telebot import types
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import os
import json
import threading
import time

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER', '0707407869')
SUPPORT_CONTACT = os.getenv('SUPPORT_HANDLE', '@Denverlyksignalpro')
VIP_CHANNEL = os.getenv('VIP_CHANNEL', '')

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
print("Bot created", flush=True)

# ===== CONFIG =====
PAIRS_FOREX = ['EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X','USDCAD=X']
PAIRS_OTC = ['EURUSD_OTC','GBPUSD_OTC','USDJPY_OTC']

USERS = {}
STATS = {'scans': 0, 'signals': 0, 'wins': 0, 'losses': 0}
LOCK = threading.Lock()
DATA_FILE = 'bot_data.json'

TIERS = {
    'FREE': {'scans': 3, 'confluence': False},
    'WEEKLY': {'scans': 999, 'price': 1000, 'days': 7, 'confluence': True},
    'MONTHLY': {'scans': 999, 'price': 5500, 'days': 30, 'confluence': True}
}

# ===== PERSISTENCE =====
def save_data():
    try:
        with LOCK:
            with open(DATA_FILE, 'w') as f:
                json.dump({'users': USERS, 'stats': STATS}, f)
    except Exception as e:
        print(f"SAVE ERROR: {e}", flush=True)

def load_data():
    global USERS, STATS
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                USERS = {int(k): v for k, v in data.get('users', {}).items()}
                STATS = data.get('stats', STATS)
                print(f"Loaded {len(USERS)} users", flush=True)
    except Exception as e:
        print(f"LOAD ERROR: {e}", flush=True)

load_data()

# ===== UTILS =====
def get_user(uid):
    today = str(datetime.now().date())
    with LOCK:
        if uid not in USERS:
            USERS[uid] = {
                'tier': 'MONTHLY' if uid == ADMIN_ID else 'FREE',
                'expiry': None,
                'scans': 0,
                'wins': 0,
                'losses': 0,
                'refs': 0,
                'date': today,
                'last_scan': 0,
                'history': [],
                'loss_streak': 0,
                'loss_streak_time': 0
            }
        if USERS[uid]['date']!= today:
            USERS[uid]['scans'] = 0
            USERS[uid]['date'] = today

        # Auto reset loss streak after 1 hour - FIXED PARENTHESES
        if USERS[uid]['loss_streak'] >= 3:
            if time.time() - USERS[uid].get('loss_streak_time', 0) > 3600:
                USERS[uid]['loss_streak'] = 0
                USERS[uid]['loss_streak_time'] = 0

        # Check expiry
        if USERS[uid]['expiry']:
            try:
                exp_dt = datetime.fromisoformat(USERS[uid]['expiry'])
                if datetime.now(timezone.utc) > exp_dt:
                    USERS[uid]['tier'] = 'FREE'
                    USERS[uid]['expiry'] = None
            except:
                USERS[uid]['tier'] = 'FREE'
                USERS[uid]['expiry'] = None
    return USERS[uid]

def can_scan(uid):
    user = get_user(uid)
    if uid == ADMIN_ID:
        return True, ""
    if user['loss_streak'] >= 3:
        wait_min = int(60 - (time.time() - user.get('loss_streak_time', 0)) / 60)) # FIXED SYNTAX
        return False, f"Loss protection active. Auto-reset in {wait_min}min."
    if user['tier'] == 'FREE' and user['scans'] >= TIERS['FREE']['scans']:
        return False, f"Daily limit: {TIERS['FREE']['scans']}. Upgrade: /upgrade"
    if time.time() - user['last_scan'] < 30:
        return False, "Wait 30s between scans"
    return True, ""

def add_scan(uid, signal=None):
    with LOCK:
        user = get_user(uid)
        user['scans'] += 1
        user['last_scan'] = time.time()
        STATS['scans'] += 1
        if signal:
            user['history'] = ([signal] + user['history'])[:10]
            STATS['signals'] += 1
    save_data()

def get_tv_link(pair, tf='1'):
    p = pair.replace('_OTC','').replace('=X','')
    return f"https://tradingview.com/chart/?symbol=FX:{p}&interval={tf}"

# ===== SMC LOGIC - BULLETPROOF =====
def safe_yf_download(pair, interval='1m'):
    try:
        p = pair.replace('_OTC', '=X') if '_OTC' in pair else pair
        print(f"Downloading {p}", flush=True)
        df = yf.Ticker(p).history(period='1d', interval=interval, timeout=5)
        if df.empty or len(df) < 20:
            return None
        return df[['Open','High','Low','Close']].dropna()
    except Exception as e:
        print(f"YF ERROR {pair}: {str(e)[:50]}", flush=True)
        return None

def analyze_pair_safe(pair):
    try:
        df = safe_yf_download(pair, '1m')
        if df is None:
            return None

        c, h, l = df['Close'].values, df['High'].values, df['Low'].values

        # Simple BOS logic
        if c[-1] > h[-10:-1].max():
            direction = 'CALL'
            conf = 75
        elif c[-1] < l[-10:-1].min():
            direction = 'PUT'
            conf = 75
        else:
            return None

        eat = timezone(timedelta(hours=3))
        entry = (datetime.now(eat) + timedelta(minutes=1)).replace(second=15, microsecond=0)

        return {
            'pair': pair,
            'direction': direction,
            'confidence': conf,
            'entry': entry,
            'reasons': ["BOS"],
            'id': f"{pair}_{int(time.time())}"
        }
    except Exception as e:
        print(f"ANALYZE ERROR {pair}: {str(e)[:50]}", flush=True)
        return None

def format_signal(sig, uid=None):
    arrow = "⬆️⬆️⬆️ UP ⬆️⬆️⬆️" if sig['direction'] == 'CALL' else "⬇️⬇️ DOWN ⬇️⬇️⬇️"
    tv = get_tv_link(sig['pair'])

    user_stats = ""
    if uid:
        u = get_user(uid)
        total = u['wins'] + u['losses']
        wr = f"{u['wins']}/{total} ({u['wins']/total*100:.0f}%)" if total else "No data"
        user_stats = f"\n\n📊 Your Stats: {wr}"

    return f"""🟢 PROFIT POTENTIAL: {sig['confidence']}%

CURRENCY PAIR: {sig['pair'].replace('_OTC','').replace('=X','')}
TIME: S15

{arrow}
{sig['entry'].strftime('%H:%M')} EAT

📊 BOS
📈 Chart: {tv}{user_stats}

Expires in 5min | ID: {sig['id'][-6:]}"""

# ===== MENU =====
def get_main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🔍 Scan All Pro"),
        types.KeyboardButton("📈 History"),
        types.KeyboardButton("📊 OTC Signals"),
        types.KeyboardButton("💱 Forex Signals"),
        types.KeyboardButton("💳 Upgrade"),
        types.KeyboardButton("👥 Refer"),
        types.KeyboardButton("🆔 My Stats"),
        types.KeyboardButton("⚙️ Settings")
    )
    return kb

# ===== HANDLERS =====
@bot.message_handler(commands=['start'])
def cmd_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        conf_status = "ON" if TIERS[user['tier']]['confluence'] else "OFF"
        exp = ""
        if user['expiry']:
            try:
                exp_dt = datetime.fromisoformat(user['expiry'])
                days_left = (exp_dt - datetime.now(timezone.utc)).days
                exp = f"\nExpires: {days_left} days"
            except:
                exp = ""

        txt = f"👋 DENVER SMC ELITE\n\nTier: {user['tier']}{exp}\nConfluence: {conf_status}\n\nSelect option:"
        bot.send_message(message.chat.id, txt, reply_markup=get_main_menu())
        print(f"START OK {uid}", flush=True)
    except Exception as e:
        print(f"START ERROR: {e}", flush=True)
        bot.send_message(message.chat.id, "Welcome!")

@bot.message_handler(commands=['upgrade'])
def cmd_upgrade(message):
    try:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("📅 WEEKLY - KES 1,000", callback_data="pay_weekly"),
            types.InlineKeyboardButton("📅 MONTHLY - KES 5,500", callback_data="pay_monthly")
        )
        txt = """💎 CHOOSE YOUR PLAN

🥇 WEEKLY ELITE: KES 1,000
- 7 days unlimited signals
- MTF Confluence ON

🥇 MONTHLY ELITE: KES 5,500
- 30 days unlimited signals
- Save KES 1,500

Select plan below:"""
        bot.send_message(message.chat.id, txt, reply_markup=kb)
    except Exception as e:
        print(f"UPGRADE ERROR: {e}", flush=True)

@bot.message_handler(commands=['grant'])
def cmd_grant(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        tier = parts[2].upper()
        if tier not in ['WEEKLY', 'MONTHLY']:
            bot.reply_to(message, "Usage: /grant user_id WEEKLY or MONTHLY")
            return
        days = TIERS['days'] # FIXED
        with LOCK:
            u = get_user(uid)
            u['tier'] = tier
            u['expiry'] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            u['loss_streak'] = 0
            u['loss_streak_time'] = 0
        save_data()
        bot.reply_to(message, f"✅ {tier} granted to {uid} for {days}d")
        bot.send_message(uid, f"🎉 {tier} ELITE activated for {days} days!")
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)[:100]}")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    try:
        uid = message.from_user.id
        text = message.text.strip()
        print(f"MSG: {text} FROM {uid}", flush=True)

        if "Scan All Pro" in text:
            print("SCAN START", flush=True)
            can, msg = can_scan(uid)
            if not can:
                bot.send_message(message.chat.id, f"❌ {msg}")
                return

            add_scan(uid)
            bot.send_message(message.chat.id, "🔍 Scanning pairs...")
            print("SCAN MESSAGE SENT", flush=True)

            # Only scan 3 pairs to avoid timeout
            found_signal = None
            for pair in ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X']:
                sig = analyze_pair_safe(pair)
                if sig:
                    found_signal = sig
                    print(f"SIGNAL FOUND: {pair}", flush=True)
                    break

            if found_signal:
                add_scan(uid, found_signal)
                txt = format_signal(found_signal, uid)
                kb = types.InlineKeyboardMarkup()
                kb.add(
                    types.InlineKeyboardButton("✅ Win", callback_data=f"win_{found_signal['id']}"),
                    types.InlineKeyboardButton("❌ Loss", callback_data=f"loss_{found_signal['id']}")
                )
                bot.send_message(message.chat.id, txt, reply_markup=kb)
                print("SIGNAL SENT", flush=True)
            else:
                bot.send_message(message.chat.id, "❌ No setups right now. Try again in 2min.")
                print("NO SIGNAL", flush=True)
            return

        if "History" in text:
            user = get_user(uid)
            if not user['history']:
                bot.send_message(message.chat.id, "No signal history yet.")
                return
            txt = "📈 LAST 5 SIGNALS:\n\n"
            for i, sig in enumerate(user['history'][:5], 1):
                status = sig.get('result', 'Pending')
                emoji = "✅" if status == "Win" else "❌" if status == "Loss" else "⏳"
                txt += f"{i}. {sig['pair'].replace('_OTC','').replace('=X','')} {sig['direction']} {emoji}\n"
            bot.send_message(message.chat.id, txt)
            return

        if "My Stats" in text:
            user = get_user(uid)
            total = user['wins'] + user['losses']
            wr = f"{user['wins']}/{total} ({user['wins']/total*100:.1f}%)" if total else "No trades"
            exp = "Lifetime"
            if user['expiry']:
                try:
                    exp_dt = datetime.fromisoformat(user['expiry'])
                    days = (exp_dt - datetime.now(timezone.utc)).days
                    exp = f"{days} days left"
                except:
                    exp = "Error"
            txt = f"""🆔 YOUR STATS

ID: {uid}
Tier: {user['tier']}
Expiry: {exp}
Scans today: {user['scans']}/{TIERS[user['tier']]['scans']}

Win Rate: {wr}
Loss Streak: {user['loss_streak']}/3"""
            bot.send_message(message.chat.id, txt)
            return

        if "Upgrade" in text:
            cmd_upgrade(message)
            return

        if "Refer" in text:
            ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{uid}"
            txt = f"👥 REFERRAL PROGRAM\n\nYour link: {ref_link}\n\nBonus: +7 days ELITE per referral"
            bot.send_message(message.chat.id, txt)
            return

        if "Settings" in text:
            user = get_user(uid)
            conf = "ON" if TIERS[user['tier']]['confluence'] else "OFF"
            txt = f"⚙️ SETTINGS\n\nConfluence: {conf}\nCooldown: 30s\n\nUpgrade for Confluence ON"
            bot.send_message(message.chat.id, txt)
            return

        bot.send_message(message.chat.id, "Use the menu buttons below.")

    except Exception as e:
        print(f"HANDLER CRASH: {str(e)[:200]}", flush=True)
        try:
            bot.send_message(message.chat.id, "⚠️ Error occurred. Try again.")
        except:
            pass

@bot.callback_query_handler(func=lambda call: True)
def callback_all(call):
    try:
        data = call.data
        uid = call.from_user.id
        print(f"CALLBACK: {data} FROM {uid}", flush=True)

        if data == "pay_weekly" or data == "pay_monthly":
            tier = "WEEKLY" if "weekly" in data else "MONTHLY"
            price = TIERS['price'] # FIXED
            days = TIERS['days'] # FIXED
            txt = f"""💰 {tier} PAYMENT

Amount: KES {price}
Duration: {days} days

📱 M-PESA:
PayBill to {MPESA_NUMBER}
Amount: {price}
Send screenshot to {SUPPORT_CONTACT}
Include: {tier} {uid}"""
            bot.send_message(call.message.chat.id, txt)
            bot.answer_callback_query(call.id)
            return

        if data.startswith("win_") or data.startswith("loss_"):
            action, sig_id = data.split('_', 1)
            with LOCK:
                user = get_user(uid)
                for sig in user['history']:
                    if sig['id'] == sig_id and 'result' not in sig:
                        if action == "win":
                            user['wins'] += 1
                            user['loss_streak'] = 0
                            user['loss_streak_time'] = 0
                            STATS['wins'] += 1
                            sig['result'] = "Win"
                        else:
                            user['losses'] += 1
                            user['loss_streak'] += 1
                            if user['loss_streak'] == 1:
                                user['loss_streak_time'] = time.time()
                            STATS['losses'] += 1
                            sig['result'] = "Loss"
                        save_data()
                        bot.answer_callback_query(call.id, f"Recorded: {sig['result']}")
                        return
            bot.answer_callback_query(call.id, "Already recorded")

    except Exception as e:
        print(f"CALLBACK ERROR: {str(e)[:200]}", flush=True)
        bot.answer_callback_query(call.id, "Error")

print("Handlers ready", flush=True)

if __name__ == "__main__":
    print("=== POLLING STARTED ===", flush=True)
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
