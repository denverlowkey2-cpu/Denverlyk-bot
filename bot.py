# force restart - April 30 2026
import sys
print("=== CONTAINER STARTED ===", flush=True)

import os
print("=== IMPORTING ===", flush=True)
import telebot
from telebot import types
import requests
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import schedule
import threading
import ta
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler

print("=== ALL IMPORTS DONE ===", flush=True)

# ===== CONFIG FROM RAILWAY VARIABLES =====
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
TD_KEY = os.getenv('TD_KEY')
SUPPORT_HANDLE = os.getenv('SUPPORT_HANDLE')
MPESA_NUMBER = os.getenv('MPESA_NUMBER')

print(f"=== TOKEN LENGTH: {len(BOT_TOKEN)} ===", flush=True)
if not BOT_TOKEN:
    print("=== ERROR: BOT_TOKEN IS EMPTY ===", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

try:
    me = bot.get_me()
    print(f"=== BOT USERNAME: @{me.username} ===", flush=True)
except Exception as e:
    print(f"=== BOT.GET_ME FAILED: {e} ===", flush=True)
    sys.exit(1)

# ===== DATABASE SETUP - USERS PERSIST ON DEPLOY =====
DB_PATH = 'bot_data.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  tier TEXT,
                  expiry TEXT,
                  expiry_notified INTEGER DEFAULT 0)''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN expiry TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN expiry_notified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def load_users():
    USERS_DATA = {}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, tier, expiry, expiry_notified FROM users")
    rows = c.fetchall()
    for row in rows:
        user_id, tier, expiry_str, notified = row
        expiry = datetime.fromisoformat(expiry_str) if expiry_str else None
        USERS_DATA[user_id] = {
            'tier': tier,
            'expiry': expiry,
            'expiry_notified': bool(notified) if notified is not None else False
        }
    conn.close()
    print(f"=== LOADED {len(USERS_DATA)} USERS FROM DB ===", flush=True)
    return USERS_DATA

def save_user(user_id, tier, expiry, expiry_notified=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    expiry_str = expiry.isoformat() if expiry else None
    c.execute("""INSERT OR REPLACE INTO users
                 (user_id, tier, expiry, expiry_notified)
                 VALUES (?,?,?,?)""",
              (user_id, tier, expiry_str, int(expiry_notified)))
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE user_id =?", (user_id,))
    conn.commit()
    conn.close()

init_db()
USERS_DATA = load_users()

# ===== PAIRS =====
PAIRS = [
    'XAUUSD', 'EURUSD', 'GBPUSD', 'BTCUSD',
    'USDJPY', 'AUDUSD', 'US30', 'NAS100',
    'EURJPY', 'GBPJPY', 'USDCAD', 'NZDUSD',
    'USDCHF', 'EURGBP', 'XAGUSD', 'GER40'
]

# ===== DATA STORAGE + CACHE =====
user_data = {}
DATA_FILE = 'user_data.json'
price_cache = {}
CACHE_DURATION = 300

# ===== MESSAGES =====
START_MSG = f"""
🔥 *DENVERLYK SIGNALS*

Choose your access level:

💰 *NORMAL - 1000 KSH / 7 Days*
✅ 10 scans per day
✅ 65%+ confidence signals
✅ Last 5 signals + settings
✅ Upgrade to VIP anytime

💎 *VIP - 2000 KSH / 7 Days*
✅ Unlimited scans
✅ 75%+ confidence only
✅ Priority alerts - 60s early
✅ Killzone pings 10AM & 3PM EAT
✅ Live data on 85%+ setups
✅ Sunday weekly outlook

*Pay via M-Pesa to:* *{MPESA_NUMBER}*
Use your @username as reference.

Pick your plan below 👇
"""

NORMAL_MSG = f"""
💰 *NORMAL ACCESS - 1000 KSH / 7 Days*

*You get:*
✅ 10 scans per day
✅ 65%+ confidence signals
✅ Track last 5 signals
✅ Custom settings

*Pay via M-Pesa:*
1. Send Money to *{MPESA_NUMBER}*
2. Amount: 1000 KSH
3. Reference: Your @username
4. Send screenshot here

Bot activates in 5-10 mins.
Upgrade to VIP anytime for 2000 KSH/week.
"""

VIP_MSG = f"""
💎 *VIP UPGRADE - 2000 KSH / 7 Days*

*You get:*
✅ Unlimited scans
✅ Priority alerts - 60s early
✅ Killzone pings - 10AM & 3PM EAT
✅ 75%+ confidence minimum
✅ Monster setups 85%+ = live data
✅ Sunday weekly outlook

*Pay via M-Pesa:*
1. Send Money to *{MPESA_NUMBER}*
2. Amount: 2000 KSH
3. Reference: Your @username
4. Send screenshot here

Bot activates in 5-10 mins.
"""

# ===== HELPER FUNCTIONS =====
def load_data():
    global user_data
    try:
        with open(DATA_FILE, 'r') as f:
            user_data = json.load(f)
    except:
        user_data = {}

def save_data():
    with open(DATA_FILE, 'w') as f:
        json.dump(user_data, f, indent=2)

def init_user(user_id, username):
    if user_id not in user_data:
        user_data[user_id] = {
            'scans_today': 0,
            'is_vip': False,
            'is_normal': False,
            'vip_expiry': None,
            'normal_expiry': None,
            'username': username,
            'last_scan_date': str(datetime.now().date()),
            'signal_history': [],
            'settings': {
                'killzone_pings': True,
                'min_confidence': 65,
                'quiet_hours': False
            }
        }
        save_data()

def sync_vip_status(user_id):
    uid = str(user_id)
    if user_id in USERS_DATA:
        tier = USERS_DATA[user_id].get('tier')
        expiry = USERS_DATA[user_id].get('expiry')
        if tier == 'VIP' and expiry and expiry > datetime.now(timezone.utc):
            user_data[uid]['is_vip'] = True
            user_data[uid]['vip_expiry'] = expiry.isoformat()
        else:
            user_data[uid]['is_vip'] = False
            user_data[uid]['vip_expiry'] = None
    else:
        user_data[uid]['is_vip'] = False
        user_data[uid]['vip_expiry'] = None

def check_subscription_expiry(user_id):
    uid = str(user_id)
    if uid not in user_data:
        return
    sync_vip_status(int(user_id))
    if user_data[uid]['is_normal']:
        expiry = datetime.fromisoformat(user_data[uid]['normal_expiry'])
        if datetime.now() > expiry:
            user_data[uid]['is_normal'] = False
            user_data[uid]['normal_expiry'] = None
            save_data()

def has_access(user_id):
    # ADMIN BYPASS - Admin always has access to signals
    if int(user_id) == ADMIN_ID:
        return True
    check_subscription_expiry(user_id)
    return user_data[user_id]['is_vip'] or user_data[user_id]['is_normal']

def is_quiet_hours(user_id):
    if not user_data[user_id]['settings']['quiet_hours']: return False
    hour = datetime.now(timezone.utc).hour
    return hour >= 19 or hour < 4

def get_td_data(pair, interval='15min', outputsize=200, force_fresh=False):
    global price_cache
    now = time.time()
    cache_key = f"{pair}_{interval}"
    if not force_fresh and cache_key in price_cache:
        if now - price_cache[cache_key]['time'] < CACHE_DURATION:
            return price_cache[cache_key]['data']
    url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval={interval}&outputsize={outputsize}&apikey={TD_KEY}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if 'code' in data and data['code'] == 429:
            return price_cache.get(cache_key, {}).get('data')
        price_cache[cache_key] = {'data': data, 'time': now}
        return data
    except:
        return price_cache.get(cache_key, {}).get('data')

def df_from_td(data):
    if not data or 'values' not in data:
        return None
    df = pd.DataFrame(data['values'])
    df = df.iloc[::-1].reset_index(drop=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

# ===== 10 STRATEGY FUNCTIONS =====
def check_killzone():
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    return (7 <= hour < 10) or (12 <= hour < 15)

def check_htf_trend(df_4h):
    if len(df_4h) < 200: return 0
    ema50 = ta.trend.ema_indicator(df_4h['close'], 50).iloc[-1]
    ema200 = ta.trend.ema_indicator(df_4h['close'], 200).iloc[-1]
    return 1 if ema50 > ema200 else -1

def detect_bos_choch(df):
    if len(df) < 20: return 0, None
    recent_high = df['high'].iloc[-20:-1].max()
    recent_low = df['low'].iloc[-20:-1].min()
    last_close = df['close'].iloc[-1]
    if last_close > recent_high: return 1, 'bullish_bos'
    if last_close < recent_low: return -1, 'bearish_bos'
    return 0, None

def detect_liquidity_sweep(df):
    if len(df) < 10: return 0
    prev_high = df['high'].iloc[-10:-2].max()
    prev_low = df['low'].iloc[-10:-2].min()
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if prev['low'] < prev_low and last['close'] > prev['low']: return 1
    if prev['high'] > prev_high and last['close'] < prev['high']: return -1
    return 0

def detect_fvg(df):
    if len(df) < 4: return 0, None
    for i in range(len(df)-3, len(df)-1):
        c1, c2, c3 = df.iloc[i-2], df.iloc[i-1], df.iloc[i]
        if c1['high'] < c3['low']:
            fvg_high, fvg_low = c3['low'], c1['high']
            if c2['close'] < (fvg_high + fvg_low)/2:
                return 1, {'high': fvg_high, 'low': fvg_low, 'type': 'bull'}
        if c1['low'] > c3['high']:
            fvg_high, fvg_low = c1['low'], c3['high']
            if c2['close'] > (fvg_high + fvg_low)/2:
                return -1, {'high': fvg_high, 'low': fvg_low, 'type': 'bear'}
    return 0, None

def detect_order_block(df):
    if len(df) < 10: return 0
    for i in range(len(df)-5, len(df)-2):
        if df['close'].iloc[i] < df['open'].iloc[i]:
            if df['close'].iloc[i+1] > df['high'].iloc[i]:
                if df['low'].iloc[-1] <= df['high'].iloc[i] and df['close'].iloc[-1] > df['low'].iloc[i]:
                    return 1
        if df['close'].iloc[i] > df['open'].iloc[i]:
            if df['close'].iloc[i+1] < df['low'].iloc[i]:
                if df['high'].iloc[-1] >= df['low'].iloc[i] and df['close'].iloc[-1] < df['high'].iloc[i]:
                    return -1
    return 0

def check_ema_pullback(df):
    if len(df) < 50: return 0
    ema50 = ta.trend.ema_indicator(df['close'], 50)
    ema200 = ta.trend.ema_indicator(df['close'], 200)
    last_close = df['close'].iloc[-1]
    last_ema50 = ema50.iloc[-1]
    if last_ema50 > ema200.iloc[-1] and abs(last_close - last_ema50) / last_close < 0.002:
        return 1
    if last_ema50 < ema200.iloc[-1] and abs(last_close - last_ema50) / last_close < 0.002:
        return -1
    return 0

def check_rsi_divergence(df):
    if len(df) < 30: return 0
    rsi = ta.momentum.rsi(df['close'], 14)
    if rsi.iloc[-1] < 30 and df['low'].iloc[-1] < df['low'].iloc[-10:-1].min():
        return 1
    if rsi.iloc[-1] > 70 and df['high'].iloc[-1] > df['high'].iloc[-10:-1].max():
        return -1
    return 0

def check_volume(df):
    if len(df) < 20 or 'volume' not in df: return 0
    avg_vol = df['volume'].iloc[-20:-1].mean()
    return 1 if df['volume'].iloc[-1] > avg_vol * 1.5 else 0

def check_daily_bias(df_1d):
    if len(df_1d) < 2: return 0
    today = df_1d.iloc[-1]
    return 1 if today['close'] > today['open'] else -1

def analyze_pair(pair, is_vip, user_min_conf):
    data_15m = get_td_data(pair, '15min', 200, force_fresh=False)
    data_4h = get_td_data(pair, '4h', 200, force_fresh=False)
    data_1d = get_td_data(pair, '1day', 30, force_fresh=False)
    df = df_from_td(data_15m)
    df_4h = df_from_td(data_4h)
    df_1d = df_from_td(data_1d)
    if df is None or len(df) < 200: return None
    confidence = 0
    direction = 0
    killzone = check_killzone()
    htf_trend = check_htf_trend(df_4h) if df_4h is not None else 0
    bos_dir, bos_type = detect_bos_choch(df)
    liq_sweep = detect_liquidity_sweep(df)
    fvg_dir, fvg_zone = detect_fvg(df)
    ob_dir = detect_order_block(df)
    ema_pb = check_ema_pullback(df)
    rsi_div = check_rsi_divergence(df)
    volume = check_volume(df)
    daily_bias = check_daily_bias(df_1d) if df_1d is not None else 0
    if bos_dir!= 0: confidence += 25; direction = bos_dir
    if fvg_dir == direction and fvg_dir!= 0: confidence += 15
    if killzone: confidence += 15
    if htf_trend == direction and htf_trend!= 0: confidence += 15
    if volume: confidence += 10
    if ema_pb == direction and ema_pb!= 0: confidence += 10
    if rsi_div == direction and rsi_div!= 0: confidence += 10
    if daily_bias == direction and daily_bias!= 0: confidence += 10
    if liq_sweep == direction: confidence += 15
    if ob_dir == direction and ob_dir!= 0: confidence += 20
    if is_vip and confidence >= 85:
        fresh_data = get_td_data(pair, '15min', 200, force_fresh=True)
        df = df_from_td(fresh_data)
        if df is not None:
            confidence = min(confidence + 5, 100)
    min_conf = 75 if is_vip else user_min_conf
    if confidence < min_conf or direction == 0: return None
    atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], 14).iloc[-1]
    last_close = df['close'].iloc[-1]
    if direction == 1:
        entry = round(last_close, 5)
        sl = round(entry - atr * 1.5, 5)
        tp1 = round(entry + atr * 1.5, 5)
        tp2 = round(entry + atr * 3, 5)
        tp3 = round(entry + atr * 4.5, 5)
    else:
        entry = round(last_close, 5)
        sl = round(entry + atr * 1.5, 5)
        tp1 = round(entry - atr * 1.5, 5)
        tp2 = round(entry - atr * 3, 5)
        tp3 = round(entry - atr * 4.5, 5)
    rr = round(abs(tp2 - entry) / abs(entry - sl), 1)
    return {
        'direction': 'BUY' if direction == 1 else 'SELL',
        'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
        'confidence': int(confidence), 'rr': f'1:{rr}',
        'is_fresh': confidence >= 85 and is_vip,
        'timestamp': datetime.now().isoformat(), 'pair': pair
    }

def format_signal(pair, signal, is_vip):
    vip_tag = "💎 *VIP SIGNAL*" if is_vip else "🔥 *SIGNAL*"
    cache_key = f"{pair}_15min"
    cache_age = int((time.time() - price_cache.get(cache_key, {}).get('time', time.time())) / 60)
    fresh_tag = "\n⚡ *LIVE DATA* - Monster setup" if signal.get('is_fresh') else ""
    return f"""
{vip_tag}{fresh_tag}

*Pair:* {pair}
*Direction:* {signal['direction']}
*Entry:* {signal['entry']}

*Stop Loss:* {signal['sl']}
*TP1:* {signal['tp1']}
*TP2:* {signal['tp2']}
*TP3:* {signal['tp3']}

*Confidence:* {signal['confidence']}%
*Risk:Reward:* {signal['rr']}
*Data age:* {'LIVE' if signal.get('is_fresh') else f'{cache_age} min'}

Trade at your own risk. Not financial advice.
"""

def save_signal_to_history(user_id, signal):
    hist = user_data[user_id]['signal_history']
    hist.insert(0, signal)
    user_data[user_id]['signal_history'] = hist[:5]
    save_data()

# ===== EXPIRY AUTO-DM =====
def check_expired_vips():
    print("=== RUNNING EXPIRY CHECK ===", flush=True)
    now = datetime.now(timezone.utc)
    expired_today = []
    for uid, data in list(USERS_DATA.items()):
        expiry = data.get('expiry')
        tier = data.get('tier')
        if tier == 'VIP' and expiry and expiry < now:
            hours_since_expiry = (now - expiry).total_seconds() / 3600
            if 0 < hours_since_expiry < 24 and not data.get('expiry_notified'):
                try:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("💎 Renew VIP - 2000 KSH/week", callback_data="choose_vip"))
                    bot.send_message(
                        uid,
                        f"😢 *VIP EXPIRED*\n\nYour VIP access ended on `{expiry.strftime('%d %b %Y')}`\n\nRenew now to keep getting 75%+ signals, killzone alerts, and unlimited scans.",
                        parse_mode='Markdown', reply_markup=markup
                    )
                    USERS_DATA[uid]['expiry_notified'] = True
                    save_user(uid, tier, expiry, True)
                    expired_today.append(uid)
                    print(f"=== SENT EXPIRY DM TO {uid} ===", flush=True)
                except Exception as e:
                    print(f"=== FAILED TO DM {uid}: {e} ===", flush=True)
    if expired_today:
        try:
            bot.send_message(ADMIN_ID, f"📧 Sent expiry DMs to `{len(expired_today)}` users", parse_mode='Markdown')
        except:
            pass

# ===== BOT COMMANDS ===== #
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    print(f"=== /START BY {user_id} ===", flush=True)
    init_user(str(user_id), message.from_user.username or message.from_user.first_name)

    # ADMIN GETS VIP MENU + ADMIN PANEL BUTTON ALWAYS - FIX 2
    if user_id == ADMIN_ID:
        print(f"=== ADMIN ACCESS FOR {user_id} ===", flush=True)
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn1 = types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal")
        btn2 = types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats")
        btn3 = types.InlineKeyboardButton("🕐 Last 5 Signals", callback_data="last_signals")
        btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
        btn5 = types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")
        markup.add(btn1, btn2, btn3, btn4, btn5)

        bot.send_message(
            message.chat.id,
            f"🔥 *Welcome Admin @Denverlyksignalpro* 🔧\n\nID: `{user_id}`\nAccess: Unlimited\n\nUse signals + manage users below:",
            parse_mode='Markdown',
            reply_markup=markup
        )
        return

    # 2. VIP CHECK FOR REGULAR USERS
    if user_id in USERS_DATA:
        user = USERS_DATA[user_id]
        expiry = user.get('expiry')
        if user.get('tier') == 'VIP' and expiry and datetime.now(timezone.utc) < expiry:
            print(f"=== VIP ACCESS GRANTED FOR {user_id} ===", flush=True)
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn1 = types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal")
            btn2 = types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats")
            btn3 = types.InlineKeyboardButton("🕐 Last 5 Signals", callback_data="last_signals")
            btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            markup.add(btn1, btn2, btn3, btn4)
            expiry_str = expiry.strftime("%d %b %Y")
            bot.send_message(message.chat.id, f"🔥 *Welcome back VIP @{message.from_user.username}*\n\nExpires: {expiry_str}\nScans: Unlimited", parse_mode='Markdown', reply_markup=markup)
            return

    # 3. DEFAULT: Payment page
    print(f"=== SHOWING PAYMENT PAGE TO {user_id} ===", flush=True)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💰 Normal - 1000 KSH/week", callback_data="choose_normal"))
    markup.add(types.InlineKeyboardButton("💎 VIP - 2000 KSH/week", callback_data="choose_vip"))
    bot.send_message(message.chat.id, START_MSG, parse_mode='Markdown', reply_markup=markup)

# ===== ADMIN COMMANDS =====
@bot.message_handler(commands=['adduser'])
def cmd_adduser(message):
    user_id = message.from_user.id
    print(f"=== /ADDUSER HIT BY {user_id} ===", flush=True)
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "Usage: `/adduser USER_ID VIP`\nExample: `/adduser 8552719664 VIP`", parse_mode='Markdown')
            return
        target_id = int(args[1])
        tier = args[2].upper()
        expiry_date = datetime.now(timezone.utc) + timedelta(days=7)
        if tier not in ['VIP', 'NORMAL']:
            bot.reply_to(message, "❌ Tier must be VIP or NORMAL")
            return
        USERS_DATA[target_id] = {'tier': tier, 'expiry': expiry_date, 'expiry_notified': False}
        save_user(target_id, tier, expiry_date, False)
        bot.reply_to(message, f"✅ Added `{target_id}` as {tier}\nExpires: `{expiry_date.strftime('%d %b %Y')}`", parse_mode='Markdown')
        print(f"=== SAVED: {target_id} ===", flush=True)
        try:
            bot.send_message(target_id, f"🎉 {tier} access activated!\n\nExpires: {expiry_date.strftime('%d %b %Y')}\n\nType /start to begin", parse_mode='Markdown')
        except:
            pass
    except ValueError:
        bot.reply_to(message, "❌ User ID must be a number")
    except Exception as e:
        print(f"=== ADDUSER ERROR: {e} ===", flush=True)
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['removeuser'])
def cmd_removeuser(message):
    user_id = message.from_user.id
    print(f"=== /REMOVEUSER HIT BY {user_id} ===", flush=True)
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        args = message.text.split()
        if len(args)!= 2:
            bot.reply_to(message, "Usage: `/removeuser USER_ID`", parse_mode='Markdown')
            return
        target_id = int(args[1])
        if target_id in USERS_DATA:
            del USERS_DATA[target_id]
            delete_user(target_id)
            print(f"=== REMOVED: {target_id} ===", flush=True)
            bot.reply_to(message, f"✅ Removed `{target_id}` from VIP", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ User `{target_id}` not found", parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, "❌ Invalid USER_ID. Must be a number")
    except Exception as e:
        print(f"=== REMOVEUSER ERROR: {e} ===", flush=True)
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['renewuser'])
def cmd_renewuser(message):
    user_id = message.from_user.id
    print(f"=== /RENEWUSER HIT BY {user_id} ===", flush=True)
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: `/renewuser USER_ID DAYS`\n\nExample: `/renewuser 123456789 7`\nDefault: 7 days", parse_mode='Markdown')
            return
        target_id = int(args[1])
        days = int(args[2]) if len(args) > 2 else 7
        if target_id not in USERS_DATA:
            bot.reply_to(message, f"❌ User `{target_id}` not found. Use `/adduser` first", parse_mode='Markdown')
            return
        current_expiry = USERS_DATA[target_id].get('expiry')
        now = datetime.now(timezone.utc)
        if current_expiry and current_expiry > now:
            new_expiry = current_expiry + timedelta(days=days)
        else:
            new_expiry = now + timedelta(days=days)
        USERS_DATA[target_id]['tier'] = 'VIP'
        USERS_DATA[target_id]['expiry'] = new_expiry
        USERS_DATA[target_id]['expiry_notified'] = False
        save_user(target_id, 'VIP', new_expiry, False)
        new_expiry_str = new_expiry.strftime("%d %b %Y %H:%M")
        bot.reply_to(message, f"✅ Renewed `{target_id}`\n\nNew expiry: `{new_expiry_str}`\nAdded: `{days} days`", parse_mode='Markdown')
        print(f"=== RENEWED: {target_id} UNTIL {new_expiry_str} ===", flush=True)
    except ValueError:
        bot.reply_to(message, "❌ Invalid USER_ID or DAYS. Must be numbers")
    except Exception as e:
        print(f"=== RENEWUSER ERROR: {e} ===", flush=True)
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['listusers'])
def cmd_listusers(message):
    user_id = message.from_user.id
    print(f"=== /LISTUSERS HIT BY {user_id} ===", flush=True)
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    if not USERS_DATA:
        bot.reply_to(message, "📂 *USER LIST*\n\nNo users in database yet.", parse_mode='Markdown')
        return
    now = datetime.now(timezone.utc)
    active_vips = []
    expired_vips = []
    for uid, data in USERS_DATA.items():
        tier = data.get('tier', 'Unknown')
        expiry = data.get('expiry')
        if expiry:
            expiry_str = expiry.strftime("%d %b %Y")
            days_left = (expiry - now).days
            status = f"✅ {days_left}d left" if expiry > now else f"❌ Expired"
            line = f"`{uid}` | {tier} | {expiry_str} | {status}"
            if expiry > now:
                active_vips.append(line)
            else:
                expired_vips.append(line)
        else:
            line = f"`{uid}` | {tier} | No expiry"
            active_vips.append(line)
    msg = f"📂 *VIP USER LIST*\n\n*Active: {len(active_vips)}*\n"
    msg += "\n".join(active_vips[:15])
    if len(active_vips) > 15:
        msg += f"\n...and {len(active_vips) - 15} more"
    if expired_vips:
        msg += f"\n\n*Expired: {len(expired_vips)}*\n"
        msg += "\n".join(expired_vips[:5])
    msg += f"\n\n*Total in DB: {len(USERS_DATA)}*"
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['clearexpired'])
def cmd_clearexpired(message):
    user_id = message.from_user.id
    print(f"=== /CLEAREXPIRED HIT BY {user_id} ===", flush=True)
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    now = datetime.now(timezone.utc)
    expired_ids = []
    for uid, data in list(USERS_DATA.items()):
        expiry = data.get('expiry')
        if expiry and expiry < now:
            expired_ids.append(uid)
            del USERS_DATA[uid]
            delete_user(uid)
    if expired_ids:
        expired_list = "\n".join([f"`{uid}`" for uid in expired_ids[:10]])
        if len(expired_ids) > 10:
            expired_list += f"\n...and {len(expired_ids) - 10} more"
        bot.reply_to(message, f"🗑️ *CLEARED EXPIRED USERS*\n\nRemoved: `{len(expired_ids)}`\n\n{expired_list}", parse_mode='Markdown')
        print(f"=== CLEARED {len(expired_ids)} EXPIRED USERS ===", flush=True)
    else:
        bot.reply_to(message, "✅ No expired users found. Database is clean.", parse_mode='Markdown')

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    user_id = message.from_user.id
    print(f"=== /BROADCAST HIT BY {user_id} ===", flush=True)
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        text = message.text.replace('/broadcast', '').strip()
        if not text:
            bot.reply_to(message, "Usage: `/broadcast YOUR MESSAGE`", parse_mode='Markdown')
            return
        sent_count = 0
        failed_count = 0
        for uid, data in USERS_DATA.items():
            if data.get('tier') == 'VIP':
                try:
                    bot.send_message(uid, f"📢 *ANNOUNCEMENT*\n\n{text}", parse_mode='Markdown')
                    sent_count += 1
                    time.sleep(0.05)
                except Exception as e:
                    print(f"Failed to send to {uid}: {e}", flush=True)
                    failed_count += 1
        bot.reply_to(message, f"✅ Broadcast sent\n\nDelivered: `{sent_count}`\nFailed: `{failed_count}`", parse_mode='Markdown')
    except Exception as e:
        print(f"=== BROADCAST ERROR: {e} ===", flush=True)
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    user_id = message.from_user.id
    print(f"=== /STATS HIT BY {user_id} ===", flush=True)
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    now = datetime.now(timezone.utc)
    total_users = len(USERS_DATA)
    active_vip = 0
    expired_vip = 0
    revenue_week = 0
    expiring_3days = 0
    expiring_today = 0
    for uid, data in USERS_DATA.items():
        tier = data.get('tier')
        expiry = data.get('expiry')
        if tier == 'VIP' and expiry:
            if expiry > now:
                active_vip += 1
                days_left = (expiry - now).days
                revenue_week += 2000
                if days_left <= 0:
                    expiring_today += 1
                elif days_left <= 3:
                    expiring_3days += 1
            else:
                expired_vip += 1
    total_vip_ever = active_vip + expired_vip
    churn_rate = (expired_vip / total_vip_ever * 100) if total_vip_ever > 0 else 0
    msg = f"""📊 *BOT STATISTICS*

*👥 USERS*
Total: `{total_users}`
Active VIP: `{active_vip}` ✅
Expired VIP: `{expired_vip}` ❌

*💰 REVENUE ESTIMATE*
This Week: `{revenue_week:,} KSH`
*Based on 2000 KSH/VIP/week*

*⚠️ CHURN ALERTS*
Expiring Today: `{expiring_today}`
Expiring in 3 Days: `{expiring_3days}`
Churn Rate: `{churn_rate:.1f}%`

*📈 GROWTH*
VIP Conversion: `{(active_vip/total_users*100) if total_users > 0 else 0:.1f}%`
"""
    bot.reply_to(message, msg, parse_mode='Markdown')

# ===== CALLBACK HANDLERS - FIXED ADMIN BUTTONS =====
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = str(call.from_user.id)
    uid = int(user_id)
    check_subscription_expiry(uid)
    init_user(user_id, call.from_user.username or call.from_user.first_name)

    if call.data == "choose_normal":
        bot.edit_message_text(NORMAL_MSG, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif call.data == "choose_vip" or call.data == "go_vip":
        bot.edit_message_text(VIP_MSG, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif call.data == "get_myid":
        user_id = call.from_user.id
        username = call.from_user.username or call.from_user.first_name
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id, 
            f"🆔 *Your Telegram ID*\n\nUser: @{username}\nID: `{user_id}`\n\n*Next steps:*\n1. Copy your ID above\n2. Pay 1000 KSH for Normal OR 2000 KSH for VIP to M-Pesa: `0111510870`\n3. Send ID + payment screenshot to @Denverlyksignalpro\n\nYou'll be activated in 5-10min ✅", 
            parse_mode='Markdown'
        )
        
    elif call.data == "get_signal":
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired. Renew to continue.")
            return

        today = str(datetime.now().date())
        if user_data[user_id]['last_scan_date']!= today:
            user_data[user_id]['scans_today'] = 0
            user_data[user_id]['last_scan_date'] = today
            save_data()

        is_vip = user_data[user_id]['is_vip'] or uid == ADMIN_ID
        if not is_vip and uid!= ADMIN_ID and user_data[user_id]['scans_today'] >= 10:
            bot.answer_callback_query(call.id, "Daily limit 10 reached. Upgrade to VIP for unlimited.")
            return

        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [types.InlineKeyboardButton(pair, callback_data=f"scan_{pair}") for pair in PAIRS]
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_menu"))
        markup.add(*buttons)
        bot.edit_message_text("Select pair to scan:", call.message.chat.id, call.message.message_id, reply_markup=markup)
      
    elif call.data == "my_stats":
        is_vip = user_data[user_id]['is_vip'] or uid == ADMIN_ID
        is_normal = user_data[user_id]['is_normal']
        scans = user_data[user_id]['scans_today']

        if uid == ADMIN_ID:
            stats = f"📊 *Your Stats*\n\nStatus: ADMIN 🔧\nScans: Unlimited\nAccess: All features"
        elif is_vip:
            expiry = user_data[user_id]['vip_expiry'][:10]
            stats = f"📊 *Your Stats*\n\nStatus: VIP 💎\nExpires: {expiry}\nScans: Unlimited"
        elif is_normal:
            expiry = user_data[user_id]['normal_expiry'][:10]
            stats = f"📊 *Your Stats*\n\nStatus: Normal 💰\nExpires: {expiry}\nScans today: {scans}/10"
        else:
            stats = "❌ No active subscription"

        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, stats, parse_mode='Markdown')

    elif call.data == "last_signals":
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired.")
            return
        hist = user_data[user_id]['signal_history']
        if not hist:
            bot.answer_callback_query(call.id, "No signals yet. Scan a pair first!")
            return
        msg = "📈 *Your Last 5 Signals*\n\n"
        for i, sig in enumerate(hist, 1):
            time_ago = datetime.fromisoformat(sig['timestamp'])
            hours = int((datetime.now() - time_ago).total_seconds() / 3600)
            msg += f"{i}. {sig['pair']} {sig['direction']} {sig['confidence']}% - {hours}h ago\n Entry: {sig['entry']} | Status: Pending 🟡\n\n"
        msg += "_Results update coming soon_"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_menu"))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

    elif call.data == "settings":
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired.")
            return
        s = user_data[user_id]['settings']
        markup = types.InlineKeyboardMarkup()
        kz_text = f"🔔 Killzone Pings: {'ON' if s['killzone_pings'] else 'OFF'}"
        conf_text = f"📊 Min Confidence: {s['min_confidence']}%"
        qh_text = f"🌙 Quiet Hours: {'ON' if s['quiet_hours'] else 'OFF'}"
        markup.add(types.InlineKeyboardButton(kz_text, callback_data="toggle_kz"))
        markup.add(types.InlineKeyboardButton(conf_text, callback_data="set_conf"))
        markup.add(types.InlineKeyboardButton(qh_text, callback_data="toggle_qh"))
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_menu"))
        bot.edit_message_text("⚙️ *Settings*\n\nCustomize your bot:", call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

    elif call.data == "toggle_kz":
        user_data[user_id]['settings']['killzone_pings'] = not user_data[user_id]['settings']['killzone_pings']
        save_data()
        bot.answer_callback_query(call.id, "Killzone pings toggled!")
        callback_handler(call)

    elif call.data == "set_conf":
        current = user_data[user_id]['settings']['min_confidence']
        new = 70 if current == 65 else 65
        user_data[user_id]['settings']['min_confidence'] = new
        save_data()
        bot.answer_callback_query(call.id, f"Min confidence set to {new}%")
        callback_handler(call)

    elif call.data == "toggle_qh":
        user_data[user_id]['settings']['quiet_hours'] = not user_data[user_id]['settings']['quiet_hours']
        save_data()
        bot.answer_callback_query(call.id, "Quiet hours toggled!")
        callback_handler(call)

    elif call.data == "back_menu":
        # FIX: Don't call start(), rebuild menu directly
        bot.answer_callback_query(call.id)
        if uid == ADMIN_ID:
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn1 = types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal")
            btn2 = types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats")
            btn3 = types.InlineKeyboardButton("🕐 Last 5 Signals", callback_data="last_signals")
            btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            btn5 = types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")
            markup.add(btn1, btn2, btn3, btn4, btn5)
            bot.edit_message_text(
                f"🔥 *Welcome Admin @Denverlyksignalpro* 🔧\n\nID: `{uid}`\nAccess: Unlimited\n\nUse signals + manage users below:",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup
            )
        else:
            # For VIP users
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn1 = types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal")
            btn2 = types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats")
            btn3 = types.InlineKeyboardButton("🕐 Last 5 Signals", callback_data="last_signals")
            btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            markup.add(btn1, btn2, btn3, btn4)
            expiry_str = user_data[user_id]['vip_expiry'][:10] if user_data[user_id]['is_vip'] else "N/A"
            bot.edit_message_text(
                f"🔥 *Welcome back VIP*\n\nExpires: {expiry_str}\nScans: Unlimited",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup
            )

    elif call.data.startswith("scan_"):
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired. Renew to continue.")
            return

        if is_quiet_hours(user_id):
            bot.answer_callback_query(call.id, "Quiet hours active. No signals 10PM-7AM EAT.")
            return

        pair = call.data.split("_")[1]
        is_vip = user_data[user_id]['is_vip'] or uid == ADMIN_ID
        user_min_conf = user_data[user_id]['settings']['min_confidence']

        bot.answer_callback_query(call.id, f"Scanning {pair}...")
        bot.edit_message_text(f"🔍 Scanning {pair} with 10 strategies... Please wait", call.message.chat.id, call.message.message_id)

        signal = analyze_pair(pair, is_vip, user_min_conf)

        # FIX: Add back buttons after scan
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Scan Again", callback_data="get_signal"))
        markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu"))

        if signal:
            user_data[user_id]['scans_today'] += 1
            save_signal_to_history(user_id, signal)
            signal_text = format_signal(pair, signal, is_vip)
            bot.edit_message_text(signal_text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)
        else:
            bot.edit_message_text(f"❌ No A+ setup on {pair} right now. We don't force trades.", call.message.chat.id, call.message.message_id, reply_markup=markup)

    # Admin panel callbacks - FIXED FakeMsg with message_id
    elif call.data == "admin_listusers":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id, msg_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
                self.message_id = msg_id
        cmd_listusers(FakeMsg(uid, call.message.chat.id, call.message.message_id))

    elif call.data == "admin_addvip":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Send: `/adduser USER_ID VIP`\nExample: `/adduser 123456789 VIP`", parse_mode='Markdown')

    elif call.data == "admin_renewvip":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Send: `/renewuser USER_ID DAYS`\nExample: `/renewuser 123456789 7`", parse_mode='Markdown')

    elif call.data == "admin_clearexpired":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id, msg_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
                self.message_id = msg_id
        cmd_clearexpired(FakeMsg(uid, call.message.chat.id, call.message.message_id))

    elif call.data == "admin_broadcast":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Send: `/broadcast YOUR MESSAGE`", parse_mode='Markdown')

    elif call.data == "admin_stats":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id, msg_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
                self.message_id = msg_id
        cmd_stats(FakeMsg(uid, call.message.chat.id, call.message.message_id))

    elif call.data == "admin_panel":
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📂 List Users", callback_data="admin_listusers"),
            types.InlineKeyboardButton("➕ Add VIP", callback_data="admin_addvip"),
            types.InlineKeyboardButton("🔄 Renew VIP", callback_data="admin_renewvip"),
            types.InlineKeyboardButton("🗑️ Clear Expired", callback_data="admin_clearexpired"),
            types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            types.InlineKeyboardButton("🔥 Bot Stats", callback_data="admin_stats"),
            types.InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")
        )
        bot.edit_message_text(
            f"🔧 *ADMIN PANEL* 🔧\n\nWelcome @Denverlyksignalpro\n\nID: `{uid}`\nTotal Users: `{len(USERS_DATA)}`",
            call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup
            )

# ===== PAYMENT AUTO-DETECTION =====
@bot.message_handler(content_types=['text', 'photo', 'document'])
def handle_payment_proof(message):
    user_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name
    keywords = ['paid', 'payment', 'screenshot', 'proof', 'mpesa', 'receipt', 'done', 'sent', 'tume', 'nimelipa']

    if message.content_type == 'text':
        text = message.text.lower()
        if any(word in text for word in keywords):
            alert_admin_payment(user_id, username, text)
            bot.reply_to(message, "✅ Payment proof received! Admin will verify and activate in 5-10 mins.")
    elif message.content_type in ['photo', 'document']:
        alert_admin_payment(user_id, username, "Sent screenshot/document")
        bot.reply_to(message, "✅ Screenshot received! Admin will verify and activate in 5-10 mins.")

def alert_admin_payment(user_id, username, content):
    alert_msg = f"""
🚨 *PAYMENT ALERT*

User: @{username}
ID: `{user_id}`
Content: {content}

Activate: `/adduser {user_id} VIP`
"""
    try:
        bot.send_message(ADMIN_ID, alert_msg, parse_mode='Markdown')
    except:
        print(f"Failed to alert admin for {user_id}")

# ===== SCHEDULED JOBS =====
def killzone_ping():
    for uid in user_data:
        if (user_data[uid]['is_vip'] or int(uid) == ADMIN_ID) and user_data[uid]['settings']['killzone_pings'] and not is_quiet_hours(uid):
            try:
                bot.send_message(int(uid), "🎯 *Killzone Active*\n\nLondon/NY session is live. Bot scanning for sniper entries...", parse_mode='Markdown')
            except:
                pass

def sunday_outlook():
    msg = "📈 *Sunday Weekly Outlook*\n\nKey levels to watch this week:\nXAUUSD: 2630 support, 2670 resistance\nEURUSD: 1.0850 key zone\n\nBot is live. Good luck this week VIP 💎"
    for uid in user_data:
        if user_data[uid]['is_vip'] or int(uid) == ADMIN_ID:
            try:
                bot.send_message(int(uid), msg, parse_mode='Markdown')
            except:
                pass

def run_schedule():
    schedule.every().day.at("07:00").do(killzone_ping)
    schedule.every().day.at("12:00").do(killzone_ping)
    schedule.every().sunday.at("17:00").do(sunday_outlook)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ===== START BOT =====
if __name__ == "__main__":
    load_data()
    print(f"Bot online: @Denverlykbot")
    print(f"Admin: {ADMIN_ID}")
    print(f"M-Pesa: {MPESA_NUMBER}")

    # Start expiry checker - runs every hour
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_expired_vips, 'interval', hours=1)
    scheduler.start()
    print("=== EXPIRY SCHEDULER STARTED ===", flush=True)

    # Run once on startup
    check_expired_vips()

    threading.Thread(target=run_schedule, daemon=True).start()
    bot.infinity_polling()
