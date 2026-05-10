import sys
print("=== SIGNAL BOT START ===", flush=True)

import telebot
from telebot import types
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, timezone
import os
import random

BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)
print("Bot object created", flush=True)

PAIRS = ['EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X','USDCAD=X','EURGBP=X']

def get_signal(pair, tf='1m'):
    try:
        period = {'1m': '1d', '5m': '5d', '15m': '5d'}[tf]
        df = yf.Ticker(pair).history(period=period, interval=tf)
        if df.empty or len(df) < 50:
            return None

        c = df['Close'].values
        h = df['High'].values
        l = df['Low'].values

        # Simple BOS + Momentum
        if c[-1] > h[-20:-1].max() and c[-1] > c[-5]:
            direction = "UP"
            conf = 70
        elif c[-1] < l[-20:-1].min() and c[-1] < c[-5]:
            direction = "DOWN"
            conf = 70
        else:
            return None

        eat = timezone(timedelta(hours=3))
        mins = {'1m': 1, '5m': 5, '15m': 15}[tf]
        entry = (datetime.now(eat) + timedelta(minutes=mins)).strftime('%H:%M')
        tf_name = {'1m': 'S15', '5m': 'S30', '15m': 'M1'}[tf]

        return f"🟢 PROFIT POTENTIAL: {conf}%\n\nCURRENCY PAIR: {pair.replace('=X','')}\nTIME: {tf_name}\nTF: {tf.upper()}\n\n⬆️⬆️⬆️ {direction} ⬆️⬆️⬆️\n{entry} EAT"
    except Exception as e:
        print(f"Error: {e}", flush=True)
        return None

@bot.message_handler(commands=['start'])
def start(message):
    print(f"START FROM {message.from_user.id}", flush=True)
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("M1", callback_data="tf_1m"),
        types.InlineKeyboardButton("M5", callback_data="tf_5m"),
        types.InlineKeyboardButton("M15", callback_data="tf_15m")
    )
    bot.send_message(message.chat.id, "👋 SMC SIGNAL BOT\n\nSelect timeframe:", reply_markup=kb)
    print(f"SENT MENU TO {message.from_user.id}", flush=True)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    try:
        tf = call.data.split('_')[1]
        bot.answer_callback_query(call.id, f"Scanning {tf}...")

        pair = random.choice(PAIRS)
        sig = get_signal(pair, tf)

        if sig:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("🔄 New Signal", callback_data=f"tf_{tf}"))
            bot.edit_message_text(sig, call.message.chat.id, call.message.message_id, reply_markup=kb)
        else:
            bot.edit_message_text(f"❌ No signal on {tf.upper()}. Try again.", call.message.chat.id, call.message.message_id)
        print(f"SIGNAL SENT FOR {tf}", flush=True)
    except Exception as e:
        print(f"CALLBACK ERROR: {e}", flush=True)

print("Handlers ready", flush=True)

if __name__ == "__main__":
    print("=== POLLING STARTED ===", flush=True)
    bot.delete_webhook(drop_pending_updates=True)
    bot.infinity_polling()
