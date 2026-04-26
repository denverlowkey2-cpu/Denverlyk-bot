import telebot
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone, time as dt_time
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

# DUAL MODE: FOREX + BINARY
MODE_CONFIG = {
    "forex": {
        "MIN_CONFLUENCE": 21, # 21/30 = 70%
        "SCAN_INTERVAL": 1320, # 22 MINUTES
        "DESCRIPTION": "Forex Mode - TP/SL Targets",
        "TYPE": "forex"
    },
    "binary": {
        "MIN_CONFLUENCE": 24, # 24/30 = 80% - higher for binary
        "SCAN_INTERVAL": 900, # 15 MINUTES - more signals
        "DESCRIPTION": "Binary Mode - Pocket Option",
        "TYPE": "binary"
    }
}

API_CALL_DELAY = 2
scanning_active = False
user_data = {} # {user_id: {"expiry": datetime, "referral_code": str, "mode": "forex", "last_scan": datetime}}
referral_data = {}

# ===== API CALL TRACKER =====
api_calls_today = 0
last_reset_date = None

bot = telebot.TeleBot(BOT_TOKEN)

# ===== EAT TIMEZONE FIX =====
def get_eat_time():
    eat = timezone(timedelta(hours=3))
    return datetime.now(eat).strftime("%H:%M:%S EAT")

def get_eat_datetime():
    eat = timezone(timedelta(hours=3))
    return datetime.now(eat)

# ===== API COUNTER =====
def reset_daily_counter():
    global api_calls_today, last_reset_date
    today = get_eat_datetime().date()
    if last_reset_date!= today:
        api_calls_today = 0
        last_reset_date = today

def increment_api_counter():
    global api_calls_today
    reset_daily_counter()
    api_calls_today += 1

# ===== MANUAL SCAN COOLDOWN CHECK =====
def can_user_scan(uid):
    if uid == ADMIN_ID:
        return True, None # Admin unlimited

    if uid not in user_data:
        user_data[uid] = {
            "expiry": datetime.now() - timedelta(days=1),
            "referral_code": generate_referral_code(uid),
            "mode": "forex",
            "last_scan": None
        }

    last_scan = user_data[uid].get("last_scan")
    if last_scan is None:
        return True, None

    # Check if last scan was today
    if last_scan.date() == get_eat_datetime().date():
        next_scan_time = (last_scan + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        return False, next_scan_time.strftime("%H:%M EAT")

    return True, None

# ===== AUTO-SCHEDULER =====
def is_trading_time():
    now = get_eat_datetime().time()
    london = dt_time(10, 0) <= now <= dt_time(13, 30)
    ny_overlap = dt_time(15, 30) <= now <= dt_time(19, 0)
    ny_session = dt_time(19, 0) <= now <= dt_time(22, 0)
    weekday = get_eat_datetime().weekday()
    if weekday >= 5:
        return False
    return london or ny_overlap or ny_session

def auto_scheduler():
    global scanning_active
    while True:
        should_scan = is_trading_time()
        if should_scan and not scanning_active:
            scanning_active = True
            print(f"[{get_eat_time()}] Auto-Analysis ON - Peak hours detected")
            try:
                bot.send_message(ADMIN_ID, f"🤖 Auto-Analysis ON\n\nTime: {get_eat_time()}")
            except: pass
        elif not should_scan and scanning_active:
            scanning_active = False
            print(f"[{get_eat_time()}] Auto-Analysis OFF - Market quiet")
            try:
                bot.send_message(ADMIN_ID, f"🤖 Auto-Analysis OFF\n\nCalls today: {api_calls_today}/800\nTime: {get_eat_time()}")
            except: pass
        time.sleep(60)

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
        increment_api_counter()
        time.sleep(API_CALL_DELAY)
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
    if strategy_num == 1:
        e9, e21 = ema(close, 9), ema(close, 21)
        if e9.iloc[-1] > e21.iloc[-1] and e9.iloc[-2] <= e21.iloc[-2]: return "BUY"
        elif e9.iloc[-1] < e21.iloc[-1] and e9.iloc[-2] >= e21.iloc[-2]: return "SELL"
    elif strategy_num == 2:
        r = rsi(close)
        if r.iloc[-1] < 30 and close.iloc[-1] > close.iloc[-2]: return "BUY"
        elif r.iloc[-1] > 70 and close.iloc[-1] < close.iloc[-2]: return "SELL"
    elif strategy_num == 3:
        ma = close.rolling(20).mean()
        std = close.rolling(20).std()
        upper, lower = ma + 2*std, ma - 2*std
        if close.iloc[-1] <= lower.iloc[-1]: return "BUY"
        elif close.iloc[-1] >= upper.iloc[-1]: return "SELL"
    elif strategy_num == 4:
        ema12, ema26 = ema(close, 12), ema(close, 26)
        macd = ema12 - ema26
        signal = ema(macd, 9)
        if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]: return "BUY"
        elif macd.iloc[-1] < signal.iloc[-1] and macd.iloc[-2] >= signal.iloc[-2]: return "SELL"
    elif strategy_num == 5:
        low14 = df['low'].rolling(14).min()
        high14 = df['high'].rolling(14).max()
        k = 100 * (close - low14) / (high14 - low14)
        if k.iloc[-1] < 20: return "BUY"
        elif k.iloc[-1] > 80: return "SELL"
    elif strategy_num == 6:
        a = atr(df)
        if close.iloc[-1] > close.iloc[-2] + a.iloc[-1]: return "BUY"
        elif close.iloc[-1] < close.iloc[-2] - a.iloc[-1]: return "SELL"
    elif strategy_num == 7:
        vol_ma = close.rolling(20).mean()
        if close.iloc[-1] > vol_ma.iloc[-1] * 1.02: return "BUY"
        elif close.iloc[-1] < vol_ma.iloc[-1] * 0.98: return "SELL"
    elif strategy_num == 8:
        body = abs(df['close'].iloc[-1] - df['open'].iloc[-1])
        wick = df['high'].iloc[-1] - df['low'].iloc[-1]
        if wick > body * 3 and df['close'].iloc[-1] > df['open'].iloc[-1]: return "BUY"
        elif wick > body * 3 and df['close'].iloc[-1] < df['open'].iloc[-1]: return "SELL"
    elif strategy_num == 9:
        e50 = ema(close, 50)
        if close.iloc[-1] > e50.iloc[-1]: return "BUY"
        elif close.iloc[-1] < e50.iloc[-1]: return "SELL"
    elif strategy_num == 10:
        if close.iloc[-1] > close.iloc[-5]: return "BUY"
        elif close.iloc[-1] < close.iloc[-5]: return "SELL"
    return None

def get_confluence(pair, user_mode):
    signals = {"BUY": 0, "SELL": 0}
    strategies_hit = []
    for tf in TIMEFRAMES:
        df = get_candles(pair, tf)
        if df is None: continue
        for i in range(1, 11):
            result = analyze_strategy(df, i)
            if result:
                signals[result] += 1
                strategies_hit.append(f"S{i}-{tf}")
    min_conf = MODE_CONFIG[user_mode]["MIN_CONFLUENCE"]
    if signals["BUY"] > signals["SELL"] and signals["BUY"] >= min_conf:
        return "BUY", signals["BUY"], strategies_hit
    elif signals["SELL"] > signals["BUY"] and signals["SELL"] >= min_conf:
        return "SELL", signals["SELL"], strategies_hit
    return None, signals["BUY"] + signals["SELL"], strategies_hit

def format_signal(pair, direction, confluence, strategies, user_mode):
    df = get_candles(pair, "1min")
    if df is None: return None
    price = df['close'].iloc[-1]
    mode_type = MODE_CONFIG[user_mode]["TYPE"]

    if mode_type == "binary":
        expiry = "5M"
        signal_text = "CALL ⬆️" if direction=="BUY" else "PUT ⬇️"
        return f"""🔥 DENVERLYK BINARY PRO 🔥

PAIR: {pair}
SIGNAL: {signal_text}
ENTRY: {price}
EXPIRY: {expiry}

CONFLUENCE: {confluence}/30
TIME: {get_eat_time()}

⚠️ 80%+ confluence only
DM {YOUR_USERNAME} for premium"""
    else:
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

CONFLUENCE: {confluence}/30
MODE: {user_mode.upper()}
TIME: {get_eat_time()}

Strategies: {', '.join(strategies[:5])}

⚠️ Educational tool only. Trade at own risk.
DM {YOUR_USERNAME} for premium"""

# ===== USER MANAGEMENT =====
def check_user_access(uid):
    if uid == ADMIN_ID: return True
    if uid not in user_data: return False
    return datetime.now() < user_data[uid]["expiry"]

def generate_referral_code(uid):
    code = f"DVK{uid}"
    referral_data[code] = uid
    return code

def get_user_mode(uid):
    if uid not in user_data:
        user_data[uid] = {
            "expiry": datetime.now() - timedelta(days=1),
            "referral_code": generate_referral_code(uid),
            "mode": "forex",
            "last_scan": None
        }
    return user_data[uid].get("mode", "forex")

# ===== DYNAMIC MENU =====
def get_main_menu(uid):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    if uid == ADMIN_ID:
        # ADMIN MENU - ONLY YOU SEE THIS
        markup.row('🔥 Analysis Alert', '🤖 Auto-Status')
        markup.row('⚙️ Settings', '📊 Stats')
        markup.row('📞 Calls', '👥 Add User')
        markup.row('👤 Balance', '🔗 Referral')
    else:
        # CLIENT MENU
        markup.row('🔥 Analysis Alert', '⚙️ Settings')
        markup.row('👤 Balance', '🔗 Referral')
    return markup

# ===== BROADCAST TO ALL PAID USERS =====
def broadcast_signal(signal_text, user_mode):
    count = 0
    for uid in list(user_data.keys()):
        if check_user_access(uid) and get_user_mode(uid) == user_mode:
            try:
                bot.send_message(uid, signal_text, parse_mode='HTML')
                count += 1
            except Exception as e:
                print(f"Failed to send to {uid}: {e}")
    try:
        bot.send_message(ADMIN_ID, signal_text, parse_mode='HTML')
    except: pass
    print(f"Broadcast sent to {count} users in {user_mode} mode")

# ===== AUTO SCANNER =====
def auto_scanner():
    global scanning_active
    while True:
        if scanning_active:
            for mode in ["forex", "binary"]:
                for pair in PAIRS:
                    if not scanning_active: break
                    direction, conf, strats = get_confluence(pair, mode)
                    if direction:
                        signal = format_signal(pair, direction, conf, strats, mode)
                        if signal:
                            broadcast_signal(signal, mode)
                time.sleep(5)
            time.sleep(900)
        else:
            time.sleep(5)

# ===== BOT HANDLERS =====
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    if uid not in user_data:
        user_data[uid] = {
            "expiry": datetime.now() - timedelta(days=1),
            "referral_code": generate_referral_code(uid),
            "mode": "forex",
            "last_scan": None
        }

    markup = get_main_menu(uid)
    bot.reply_to(message, f"""Welcome to Denverlyk Signal Pro 📊

10 AI Strategies | 4 Pairs | 1m-5m-15m Analysis
Modes: Forex + Binary/Pocket Option

Your Mode: {get_user_mode(uid).upper()}
Manual Scans: 1 per day for free tier protection
Auto Signals: Unlimited during peak hours

DM {YOUR_USERNAME} for premium access

⚠️ Educational tool only.""", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == '🔥 Analysis Alert')
def manual_scan(message):
    uid = message.from_user.id
    if not check_user_access(uid):
        bot.reply_to(message, f"⛔ Premium only. DM {YOUR_USERNAME}")
        return

    # CHECK DAILY LIMIT
    can_scan, next_time = can_user_scan(uid)
    if not can_scan:
        bot.reply_to(message, f"""⛔ Daily scan limit reached

You can scan again after: {next_time} tomorrow

Auto-signals still work during peak hours:
10:00-13:30, 15:30-22:00 EAT

This limit protects our free API tier.""")
        return

    user_mode = get_user_mode(uid)
    bot.reply_to(message, f"🔍 Scanning 4 pairs in {user_mode.upper()} mode... Please wait 30s")

    # UPDATE LAST SCAN TIME
    user_data[uid]["last_scan"] = get_eat_datetime()

    found = False
    for pair in PAIRS:
        direction, conf, strats = get_confluence(pair, user_mode)
        if direction:
            signal = format_signal(pair, direction, conf, strats, user_mode)
            if signal:
                bot.send_message(uid, signal, parse_mode='HTML')
                found = True
                break
    if not found:
        min_conf = MODE_CONFIG[user_mode]["MIN_CONFLUENCE"]
        bot.reply_to(message, f"No setup found with {min_conf}/30 confluence.\n\nYour next manual scan: Tomorrow 00:00 EAT\nAuto-signals active during peak hours.")

@bot.message_handler(func=lambda m: m.text == '⚙️ Settings')
def settings(message):
    uid = message.from_user.id
    current_mode = get_user_mode(uid)
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(
        telebot.types.InlineKeyboardButton("📈 Forex TP/SL", callback_data="set_mode_forex"),
        telebot.types.InlineKeyboardButton("🎯 Binary 5M", callback_data="set_mode_binary")
    )
    bot.reply_to(message, f"""⚙️ Trading Mode Settings

Current Mode: {current_mode.upper()}

📈 Forex: TP/SL targets, 70% confluence
🎯 Binary: CALL/PUT 5M expiry, 80% confluence

Pick your mode below:""", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_mode_'))
def callback_set_mode(call):
    uid = call.from_user.id
    new_mode = call.data.replace('set_mode_', '')
    if uid not in user_data:
        user_data[uid] = {"expiry": datetime.now() - timedelta(days=1), "referral_code": generate_referral_code(uid), "last_scan": None}
    user_data[uid]["mode"] = new_mode
    cfg = MODE_CONFIG[new_mode]
    bot.edit_message_text(
        f"✅ Mode switched to {new_mode.upper()}\n\n{cfg['DESCRIPTION']}\nMin Confluence: {cfg['MIN_CONFLUENCE']}/30\n\nYou’ll now receive {new_mode} signals.",
        call.message.chat.id,
        call.message.message_id
    )

@bot.message_handler(func=lambda m: m.text == '🤖 Auto-Status' and m.from_user.id == ADMIN_ID)
def auto_status(message):
    status = "ON ✅ Auto-Scheduled" if scanning_active else "OFF ❌ Outside trading hours"
    next_window = "10:00-13:30, 15:30-22:00 EAT Mon-Fri"
    bot.reply_to(message, f"🤖 Auto-Analysis: {status}\n\nActive Windows: {next_window}\nScheduler is running.")

@bot.message_handler(func=lambda m: m.text == '👤 Balance')
def balance(message):
    uid = message.from_user.id
    if uid == ADMIN_ID:
        bot.reply_to(message, "👑 Admin Access - Unlimited")
        return
    if uid in user_data and check_user_access(uid):
        expiry = user_data[uid]["expiry"]
        days = (expiry - datetime.now()).days
        last_scan = user_data[uid].get("last_scan")
        scan_status = "Available ✅" if last_scan is None or last_scan.date()!= get_eat_datetime().date() else "Used today ❌"
        bot.reply_to(message, f"✅ Premium Active\n\nExpires: {expiry.strftime('%d %b %Y')}\nDays left: {days}\nMode: {get_user_mode(uid).upper()}\nManual Scan: {scan_status}")
    else:
        bot.reply_to(message, f"❌ No active subscription\n\nDM {YOUR_USERNAME} for KSh 800/week")

@bot.message_handler(func=lambda m: m.text == '🔗 Referral')
def referral(message):
    uid = message.from_user.id
    if uid not in user_data:
        user_data[uid] = {
            "expiry": datetime.now() - timedelta(days=1),
            "referral_code": generate_referral_code(uid),
            "mode": "forex",
            "last_scan": None
        }
    code = user_data[uid]["referral_code"]
    bot.reply_to(message, f"""🔗 Your Referral Link:

`https://t.me/{bot.get_me().username}?start={code}`

Refer 1 friend who pays → You get +3 days FREE
Refer 3 friends → Get 1 WEEK FREE""")

@bot.message_handler(func=lambda m: m.text == '👥 Add User' and m.from_user.id == ADMIN_ID)
def add_user_prompt(message):
    bot.reply_to(message, "Send: /adduser USER_ID DAYS\nExample: /adduser 123456789 7")

@bot.message_handler(commands=['adduser'])
def add_user(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        args = message.text.split()
        target_id = int(args[1])
        days = int(args[2])
        if target_id not in user_data:
            user_data[target_id] = {
                "expiry": datetime.now(),
                "referral_code": generate_referral_code(target_id),
                "mode": "forex",
                "last_scan": None
            }
        user_data[target_id]["expiry"] = datetime.now() + timedelta(days=days)
        bot.reply_to(message, f"✅ Added user {target_id} for {days} days")
        try:
            bot.send_message(target_id, f"🎉 Premium Activated!\n\nAccess: {days} days\nExpires: {user_data[target_id]['expiry'].strftime('%d %b %Y')}\nMode: {get_user_mode(target_id).upper()}\n\nManual Scans: 1 per day\nTap ⚙️ Settings to choose Forex or Binary.")
        except: pass
    except Exception as e:
        bot.reply_to(message, f"Usage: /adduser USER_ID DAYS\nError: {e}")

@bot.message_handler(func=lambda m: m.text == '📊 Stats' and m.from_user.id == ADMIN_ID)
def stats(message):
    total = len(user_data)
    active = sum(1 for uid in user_data if check_user_access(uid))
    trading_now = "YES" if is_trading_time() else "NO"
    reset_daily_counter()
    forex_users = sum(1 for uid in user_data if get_user_mode(uid) == "forex" and check_user_access(uid))
    binary_users = sum(1 for uid in user_data if get_user_mode(uid) == "binary" and check_user_access(uid))
    scans_today = sum(1 for uid in user_data if user_data[uid].get("last_scan") and user_data[uid]["last_scan"].date() == get_eat_datetime().date())
    bot.reply_to(message, f"""📊 Stats

Total Users: {total}
Active Premium: {active}
├ Forex Mode: {forex_users}
└ Binary Mode: {binary_users}
Scanning: {'ON' if scanning_active else 'OFF'}
Peak Hours Now: {trading_now}
Manual Scans Today: {scans_today}
API Calls Today: {api_calls_today}/800
Pairs: {len(PAIRS)}""")

@bot.message_handler(func=lambda m: m.text == '📞 Calls' and m.from_user.id == ADMIN_ID)
def calls_command(message):
    reset_daily_counter()
    calls_per_scan = len(PAIRS) * len(TIMEFRAMES)
    scans_done = api_calls_today // calls_per_scan if calls_per_scan > 0 else 0
    scans_left = (800 - api_calls_today) // calls_per_scan
    percentage = round((api_calls_today / 800) * 100, 1)
    scans_today = sum(1 for uid in user_data if user_data[uid].get("last_scan") and user_data[uid]["last_scan"].date() == get_eat_datetime().date())
    bot.reply_to(message, f"""📞 API Usage Today

Used: {api_calls_today}/800 calls ({percentage}%)
Remaining: {800 - api_calls_today} calls
Auto Scans Done: {scans_done}
Manual Scans Used: {scans_today}
Est. Scans Left: {scans_left}

Status: {'🟢 Safe' if api_calls_today < 600 else '🟡 Getting High' if api_calls_today < 750 else '🔴 Near Limit'}
Time: {get_eat_time()}""")

# ===== START BOT =====
if __name__ == "__main__":
    print("Denverlyk Ultra v5.4 Starting - 1 Scan/Day Limit")
    scanner_thread = threading.Thread(target=auto_scanner, daemon=True)
    scanner_thread.start()
    print("Auto-scanner thread started")
    scheduler_thread = threading.Thread(target=auto_scheduler, daemon=True)
    scheduler_thread.start()
    print("Auto-scheduler started - Active: 10:00-13:30, 15:30-22:00 EAT Mon-Fri")
    bot.infinity_polling()
