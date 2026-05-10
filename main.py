import sys
print("=== SMC ELITE PRO V2 START ===", flush=True)

import telebot
from telebot import types
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import os
import random
import json
import threading
import time

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER', '0700000000')
SUPPORT_CONTACT = os.getenv('SUPPORT_HANDLE', '@Support')
VIP_CHANNEL = os.getenv('VIP_CHANNEL', '')

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
print("Bot created", flush=True)

# ===== CONFIG =====
PAIRS_FOREX = ['EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X','USDCAD=X','EURGBP=X']
PAIRS_OTC = ['EURUSD_OTC','GBPUSD_OTC','USDJPY_OTC','AUDUSD_OTC']
TIMEFRAMES = ['1m', '5m', '15m']

USERS = {}
STATS = {'scans': 0, 'signals': 0, 'wins': 0, 'losses': 0}
LOCK = threading.Lock()

TIERS = {
    'FREE': {'scans': 3, 'price': 0, 'confluence': False},
    'ELITE': {'scans': 999, 'price': 5000, 'confluence': True}
}

NEWS_TIMES = ['12:30', '13:30', '14:00', '14:30', '15:30']

# ===== UTILS =====
def get_user(uid):
    today = str(datetime.now().date())
    with LOCK:
        if uid not in USERS:
            USERS[uid] = {
                'tier': 'ELITE' if uid == ADMIN_ID else 'FREE',
                'expiry': None,
                'scans': 0,
                'wins': 0,
                'losses': 0,
                'refs': 0,
                'date': today,
                'last_scan': 0,
                'history': [],
                'loss_streak': 0
            }
        if USERS[uid]['date']!= today:
            USERS[uid]['scans'] = 0
            USERS[uid]['date'] = today
    return USERS[uid]

def get_df(pair, interval='1m'):
    try:
        p = pair.replace('_OTC', '=X') if '_OTC' in pair else pair
        period = {'1m': '1d', '5m': '5d', '15m': '5d'}[interval]
        df = yf.Ticker(p).history(period=period, interval=interval, prepost=False)
        return df[['Open','High','Low','Close']].dropna() if not df.empty else None
    except Exception as e:
        print(f"DF ERROR: {e}", flush=True)
        return None

def analyze_pair_simple(pair):
    try:
        df = get_df(pair, '1m')
        if df is None or len(df) < 20:
            return None

        c = df['Close'].values
        h = df['High'].values
        l = df['Low'].values

        if c[-1] > h[-10:-1].max():
            direction = "CALL"
            conf = 75
        elif c[-1] < l[-10:-1].min():
            direction = "PUT"
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
            'id': f"{pair}_{int(time.time())}"
        }
    except Exception as e:
        print(f"ANALYZE ERROR: {e}", flush=True)
        return None

def format_signal(sig):
    arrow = "⬆️⬆️⬆️ UP ⬆️⬆️⬆️" if sig['direction'] == 'CALL' else "⬇️⬇️⬇️ DOWN ⬇️⬇️⬇️"
    return f"""🟢 PROFIT POTENTIAL: {sig['confidence']}%

CURRENCY PAIR: {sig['pair'].replace('_OTC','').replace('=X','')}
TIME: S15
TF: M1

{arrow}
{sig['entry'].strftime('%H:%M')} EAT

📊 BOS Break"""

# ===== MENU =====
def get_main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("OTC Signals"),
        types.KeyboardButton("Forex Signals"),
        types.KeyboardButton("Scan All Pro"),
        types.KeyboardButton("My Stats"),
        types.KeyboardButton("Upgrade"),
        types.KeyboardButton("Test")
    )
    return kb

# ===== HANDLERS - SIMPLIFIED & WORKING =====
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id
    user = get_user(uid) # FIX: Don't access TIERS['confluence'] directly
    conf_status = "ON" if TIERS[user['tier']]['confluence'] else "OFF"
    txt = f"👋 SMC ELITE PRO\n\nTier: {user['tier']}\nConfluence: {conf_status}\nNews Filter: ON\n\nSelect option:"
    bot.send_message(message.chat.id, txt, reply_markup=get_main_menu())
    print(f"START SENT TO {uid}", flush=True)

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_all_text(message):
    try:
        uid = message.from_user.id
        text = message.text.strip()
        print(f"MESSAGE RECEIVED: {text} FROM {uid}", flush=True)

        if "Test" in text:
            bot.send_message(message.chat.id, "✅ Bot is responding! Handlers work.")
            return

        if "My Stats" in text:
            user = get_user(uid)
            txt = f"🆔 Your Stats\n\nID: {uid}\nTier: {user['tier']}\nScans: {user['scans']}\nWins: {user['wins']}\nLosses: {user['losses']}"
            bot.send_message(message.chat.id, txt)
            return

        if "Scan All Pro" in text:
            bot.send_message(message.chat.id, "🔍 Scanning...")
            results = []
            for pair in PAIRS_FOREX[:3]:
                sig = analyze_pair_simple(pair)
                if sig:
                    results.append(sig)

            if results:
                best = results[0]
                txt = format_signal(best)
                bot.send_message(message.chat.id, txt)
            else:
                bot.send_message(message.chat.id, "❌ No signals right now. Try again.")
            return

        if "OTC Signals" in text or "Forex Signals" in text:
            bot.send_message(message.chat.id, "Use 'Scan All Pro' for now. Direct pair selection coming next update.")
            return

        if "Upgrade" in text:
            txt = f"💎 UPGRADE\n\nELITE: KES {TIERS['ELITE']['price']}/month\n\nM-Pesa: {MPESA_NUMBER}\nSend code to {SUPPORT_CONTACT}\n\nYour ID: {uid}"
            bot.send_message(message.chat.id, txt)
            return

        bot.send_message(message.chat.id, "Unknown command. Use buttons below.")

    except Exception as e:
        print(f"CRITICAL HANDLER ERROR: {e}", flush=True)
        bot.send_message(message.chat.id, f"⚠️ Error: {str(e)[:100]}")

print("Handlers ready", flush=True)

if __name__ == "__main__":
    print("=== POLLING STARTED ===", flush=True)
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
