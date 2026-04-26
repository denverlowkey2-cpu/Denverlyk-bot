import telebot
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import threading

import os
BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
YOUR_USERNAME = "@Denverlyksignalpro"

# 4 PAIRS FREE TIER OPTIMIZED
PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
TIMEFRAMES = ["1min", "5min", "15min"]

MODE_CONFIG = {
    "normal": {
        "MIN_CONFLUENCE": 7,
        "SCAN_INTERVAL": 1320, # 22 MINUTES = 780 calls/day safe
        "DESCRIPTION": "Quality Mode - 4 Pairs Free"
    },
    "hf": {
        "MIN_CONFLUENCE": 6,
        "SCAN_INTERVAL": 1320, # Same as normal on free tier
        "DESCRIPTION": "HF Mode - Limited on Free Tier"
    }
}

API_CALL_DELAY = 2 # Seconds between API calls to avoid 429
CURRENT_MODE = "normal"
scanning_active = False
user_data = {} # {user_id: {"expiry": datetime, "referral_code": str, "referred_by": int}}
referral_data = {} # {referral_code: user_id}

bot = telebot.TeleBot(BOT_TOKEN)

# ===== STRATEGY FUNCTIONS =====
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

def get_candles(pair, interval):
    try:
        time.sleep(API_CALL_DELAY) # Rate limit protection
        url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval={interval}&apikey={TWELVE_DATA_API_KEY}&outputsize=100"
        response = requests.get(url, timeout=10)
        data = response.json()
        if "values" not in data:
            print(f"API Error for {pair} {interval}: {data}")
            return None
        df = pd.DataFrame(data["values"])
        df = df.iloc[::-1].reset_index(drop=True)
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching {pair}: {e}")
        return None

def analyze_strategy(df, strategy_num):
    if df is None or len(df) < 50:
        return None

    close = df['close']
    last = close.iloc[-1]

    # 10 Strategies
    if strategy_num == 1: # EMA Cross
        e9, e21 = ema(close, 9), ema(close, 21)
        if e9.iloc[-1] > e21.iloc[-1] and e9.iloc[-2] <= e21.iloc[-2]:
            return "BUY"
        elif e9.iloc[-1] < e21.iloc[-1] and e9.iloc[-2] >= e21.iloc[-2]:
            return "SELL"

    elif strategy_num == 2: # RSI Divergence
        r = rsi(close)
        if r.iloc[-1] < 30 and close.iloc[-1] > close.iloc[-2]:
            return "BUY"
        elif r.iloc[-1] > 70 and close.iloc[-1] < close.iloc[-2]:
            return "SELL"

    elif strategy_num == 3: # Bollinger Bounce
        ma = close.rolling(20).mean()
        std = close.rolling(20).std()
        upper, lower = ma + 2*std, ma - 2*std
        if close.iloc[-1] <= lower.iloc[-1]:
            return "BUY"
        elif close.iloc[-1] >= upper.iloc[-1]:
            return "SELL"

    elif strategy_num == 4: # MACD
        ema12, ema26 = ema(close, 12), ema(close, 26)
        macd = ema12 - ema26
        signal = ema(macd, 9)
        if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]:
            return "BUY"
        elif macd.iloc[-1] < signal.iloc[-1] and macd.iloc[-2] >= signal.iloc[-2]:
            return "SELL"

    elif strategy_num == 5: # Stochastic
        low14 = df['low'].rolling(14).min()
        high14 = df['high'].rolling(14).max()
        k = 100 * (close - low14) / (high14 - low14)
        if k.iloc[-1] < 20:
            return "BUY"
        elif k.iloc[-1] > 80:
            return "SELL"

    elif strategy_num == 6: # ATR Breakout
        a = atr(df)
        if close.iloc[-1] > close.iloc[-2] + a.iloc[-1]:
            return "BUY"
        elif close.iloc[-1] < close.iloc[-2] - a.iloc[-1]:
            return "SELL"

    elif strategy_num == 7: # Volume Spike - simplified
        vol_ma = close.rolling(20).mean()
        if close.iloc[-1] > vol_ma.iloc[-1] * 1.02:
            return "BUY"
        elif close.iloc[-1] < vol_ma.iloc[-1] * 0.98:
            return "SELL"

    elif strategy_num == 8: # Price Action Pin Bar
        body = abs(df['close'].iloc[-1] - df['open'].iloc[-1])
        wick = df['high'].iloc[-1] - df['low'].iloc[-1]
        if wick > body * 3 and df['close'].iloc[-1] > df['open'].iloc[-1]:
            return "BUY"
        elif wick > body * 3 and df['close'].iloc[-1] < df['open'].iloc[-1]:
            return "SELL"

    elif strategy_num == 9: # Trend Filter
        e50 = ema(close, 50)
        if close.iloc[-1] > e50.iloc[-1]:
            return "BUY"
        elif close.iloc[-1] < e50.iloc[-1]:
            return "SELL"

    elif strategy_num == 10: # Momentum
        if close.iloc[-1] > close.iloc[-5]:
            return "BUY"
        elif close.iloc[-1] < close.iloc[-5]:
            return "SELL"

    return None

def get_confluence(pair):
    signals = {"BUY": 0, "SELL": 0}
    strategies_hit = []

    for tf in TIMEFRAMES:
        df = get_candles(pair, tf)
        if df is None:
            continue
        for i in range(1, 11):
            result = analyze_strategy(df, i)
            if result:
                signals[result] += 1
                strategies_hit.append(f"S{i}-{tf}")

    total = signals["BUY"] + signals["SELL"]
    if signals["BUY"] > signals["SELL"] and signals["BUY"] >= MODE_CONFIG[CURRENT_MODE]["MIN_CONFLUENCE"]:
        return "BUY", signals["BUY"], strategies_hit
    elif signals["SELL"] > signals["BUY"] and signals["SELL"] >= MODE_CONFIG[CURRENT_MODE]["MIN_CONFLUENCE"]:
        return "SELL", signals["SELL"], strategies_hit
    return None, total, strategies_hit

def format_signal(pair, direction, confluence, strategies):
    df = get_candles(pair, "1min")
    if df is None:
        return None
    price = df['close'].iloc[-1]
    a = atr(df).iloc[-1]

    if direction == "BUY":
        sl = round(price - a * 1.5, 5)
        tp = round(price + a * 2, 5)
        arrow = "⬆️"
    else:
        sl = round(price + a * 1.5, 5)
        tp = round(price - a * 2, 5)
        arrow = "⬇️"

    return f"""🔥 DENVERLYK SIGNAL PRO 🔥

PAIR: {pair}
DIRECTION: {direction} {arrow}
ENTRY: {price}
SL: {sl}
TP: {tp}
EXPIRY: 1min

CONFLUENCE: {confluence}/30
MODE: {CURRENT_MODE.upper()}
TIME: {datetime.now().strftime('%H:%M:%S')} EAT

Strategies: {', '.join(strategies[:5])}

⚠️ Educational tool only. Trade at own risk.
DM {YOUR_USERNAME} for premium"""

# ===== USER MANAGEMENT =====
def check_user_access(uid):
    if uid == ADMIN_ID:
        return True
    if uid not in user_data:
        return False
    return datetime.now() < user_data[uid]["expiry"]

def generate_referral_code(uid):
    code = f"DVK{uid}"
    referral_data[code] = uid
    return code

# ===== BROADCAST TO ALL PAID USERS =====
def broadcast_signal(signal_text):
    count = 0
    for uid in list(user_data.keys()):
        if check_user_access(uid):
            try:
                bot.send_message(uid, signal_text, parse_mode='HTML')
                count += 1
            except Exception as e:
                print(f"Failed to send to {uid}: {e}")
    # Always send to admin
    if ADMIN_ID not in user_data:
        try:
            bot.send_message(ADMIN_ID, signal_text, parse_mode='HTML')
        except: pass
    print(f"Broadcast sent to {count} users")

# ===== AUTO SCANNER =====
def auto_scanner():
    global scanning_active
    while True:
        if scanning_active:
            cfg = MODE_CONFIG[CURRENT_MODE]
            for pair in PAIRS:
                if not scanning_active:
                    break
                direction, conf, strats = get_confluence(pair)
                if direction:
                    signal = format_signal(pair, direction, conf, strats)
                    if signal:
                        broadcast_signal(signal)
            time.sleep(cfg["SCAN_INTERVAL"])
        else:
            time.sleep(5)

# ===== BOT HANDLERS =====
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('🔥 Analysis Alert', '🤖 Auto-Analysis')
    markup.row('👤 Balance', '🔗 Referral')

    if uid not in user_data:
        user_data[uid] = {
            "expiry": datetime.now() - timedelta(days=1),
            "referral_code": generate_referral_code(uid),
            "referred_by": None
        }

    bot.reply_to(message, f"""Welcome to Denverlyk Signal Pro 📊

10 AI Strategies | 4 Pairs | 1m-5m-15m Analysis

Free users: Use /balance to check status
Premium: Get auto signals 24/7

DM {YOUR_USERNAME} for premium access

⚠️ Educational tool only.""", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == '🔥 Analysis Alert')
def manual_scan(message):
    uid = message.from_user.id
    if not check_user_access(uid):
        bot.reply_to(message, f"⛔ Premium only. DM {YOUR_USERNAME}")
        return

    bot.reply_to(message, "🔍 Scanning 4 pairs... Please wait 30s")
    found = False
    for pair in PAIRS:
        direction, conf, strats = get_confluence(pair)
        if direction:
            signal = format_signal(pair, direction, conf, strats)
            if signal:
                bot.send_message(uid, signal, parse_mode='HTML')
                found = True
                break
    if not found:
        bot.reply_to(message, "No high-confluence setup found right now. Market scanning...")

@bot.message_handler(func=lambda m: m.text == '🤖 Auto-Analysis')
def toggle_auto_analysis(message):
    global scanning_active
    uid = message.from_user.id

    # ADMIN ONLY - CLIENTS CANNOT TOGGLE
    if uid!= ADMIN_ID:
        bot.reply_to(message, f"""⛔ Auto-Analysis controlled by @Denverlyksignalpro

You receive signals automatically when admin activates it.
Current mode: {CURRENT_MODE.upper()}

Tap 🔥 Analysis Alert for manual scan.""")
        return

    scanning_active = not scanning_active
    cfg = MODE_CONFIG[CURRENT_MODE]
    status = "ON ✅ Broadcasting to all paid users" if scanning_active else "OFF ❌"

    if scanning_active:
        # Notify all paid users
        for user_id in list(user_data.keys()):
            if check_user_access(user_id) and user_id!= ADMIN_ID:
                try:
                    bot.send_message(user_id, f"🤖 Auto-Analysis ACTIVATED\n\nScanning 4 pairs every {cfg['SCAN_INTERVAL']//60}min\nMode: {CURRENT_MODE.upper()}\n\nYou’ll receive signals automatically.")
                except: pass

    bot.reply_to(message, f"🤖 Auto-Analysis: {status}\n\nPairs: {len(PAIRS)}\nInterval: {cfg['SCAN_INTERVAL']//60}min\nMin Confluence: {cfg['MIN_CONFLUENCE']}/30")

@bot.message_handler(func=lambda m: m.text == '👤 Balance')
def balance(message):
    uid = message.from_user.id
    if uid == ADMIN_ID:
        bot.reply_to(message, "👑 Admin Access - Unlimited")
        return
    if uid in user_data and check_user_access(uid):
        expiry = user_data[uid]["expiry"]
        days = (expiry - datetime.now()).days
        bot.reply_to(message, f"✅ Premium Active\n\nExpires: {expiry.strftime('%d %b %Y')}\nDays left: {days}")
    else:
        bot.reply_to(message, f"❌ No active subscription\n\nDM {YOUR_USERNAME} for KSh 800/week")

@bot.message_handler(func=lambda m: m.text == '🔗 Referral')
def referral(message):
    uid = message.from_user.id
    if uid not in user_data:
        user_data[uid] = {
            "expiry": datetime.now() - timedelta(days=1),
            "referral_code": generate_referral_code(uid),
            "referred_by": None
        }
    code = user_data[uid]["referral_code"]
    bot.reply_to(message, f"""🔗 Your Referral Link:

`https://t.me/{bot.get_me().username}?start={code}`

Refer 1 friend who pays → You get +3 days FREE
Refer 3 friends → Get 1 WEEK FREE

Share this link. They must use it to /start.""")

@bot.message_handler(commands=['adduser'])
def add_user(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        args = message.text.split()
        target_id = int(args[1])
        days = int(args[2])

        if target_id not in user_data:
            user_data[target_id] = {
                "expiry": datetime.now(),
                "referral_code": generate_referral_code(target_id),
                "referred_by": None
            }

        user_data[target_id]["expiry"] = datetime.now() + timedelta(days=days)
        bot.reply_to(message, f"✅ Added user {target_id} for {days} days")

        try:
            bot.send_message(target_id, f"🎉 Premium Activated!\n\nAccess: {days} days\nExpires: {user_data[target_id]['expiry'].strftime('%d %b %Y')}\n\nTap 🤖 Auto-Analysis to start.")
        except: pass

    except Exception as e:
        bot.reply_to(message, f"Usage: /adduser USER_ID DAYS\nError: {e}")

@bot.message_handler(commands=['mode'])
def switch_mode(message):
    global CURRENT_MODE
    if message.from_user.id!= ADMIN_ID:
        cfg = MODE_CONFIG[CURRENT_MODE]
        bot.reply_to(message, f"Current Mode: {CURRENT_MODE.upper()}\n{cfg['DESCRIPTION']}")
        return

    args = message.text.split()
    if len(args) > 1 and args[1].lower() in ['normal', 'hf']:
        CURRENT_MODE = args[1].lower()
        cfg = MODE_CONFIG[CURRENT_MODE]
        bot.reply_to(message, f"✅ Mode switched to {CURRENT_MODE.upper()}\n\n{cfg['DESCRIPTION']}\nScan: Every {cfg['SCAN_INTERVAL']//60}min")
    else:
        bot.reply_to(message, "Usage: /mode normal OR /mode hf")

@bot.message_handler(commands=['stats'])
def stats(message):
    if message.from_user.id!= ADMIN_ID:
        return
    total = len(user_data)
    active = sum(1 for uid in user_data if check_user_access(uid))
    bot.reply_to(message, f"📊 Stats\n\nTotal Users: {total}\nActive Premium: {active}\nScanning: {'ON' if scanning_active else 'OFF'}\nMode: {CURRENT_MODE.upper()}\nPairs: {len(PAIRS)}")

# ===== START BOT =====
if __name__ == "__main__":
    print("Denverlyk Ultra v4.2 Starting...")
    scanner_thread = threading.Thread(target=auto_scanner, daemon=True)
    scanner_thread.start()
    print("Auto-scanner thread started")
    bot.infinity_polling()
