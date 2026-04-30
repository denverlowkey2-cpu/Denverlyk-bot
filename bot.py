# force restart - April 30 2026
import sys
print("=== CONTAINER STARTED ===", flush=True)

import os
print("=== IMPORTING TELEBOT ===", flush=True)
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

print("=== ALL IMPORTS DONE ===", flush=True)

# ===== CONFIG FROM RAILWAY VARIABLES =====
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
USERS_DATA = {}  
TD_KEY = os.getenv('TD_KEY')
SUPPORT_HANDLE = os.getenv('SUPPORT_HANDLE')
MPESA_NUMBER = os.getenv('MPESA_NUMBER')

print(f"=== TOKEN LENGTH: {len(BOT_TOKEN)} ===", flush=True)
print(f"=== TOKEN START: {BOT_TOKEN[:10]}... ===", flush=True)

if not BOT_TOKEN:
    print("=== ERROR: BOT_TOKEN IS EMPTY ===", flush=True)
    sys.exit(1)

print("=== CREATING BOT OBJECT ===", flush=True)
bot = telebot.TeleBot(BOT_TOKEN)

print("=== TESTING BOT.GET_ME ===", flush=True)
try:
    me = bot.get_me()
    print(f"=== BOT USERNAME: @{me.username} ===", flush=True)
except Exception as e:
    print(f"=== BOT.GET_ME FAILED: {e} ===", flush=True)
    sys.exit(1)

print("=== STARTING POLLING ===", flush=True)

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

def check_subscription_expiry(user_id):
    uid = str(user_id)
    if uid not in user_data:
        return

    # Check VIP expiry
    if user_data[uid]['is_vip']:
        expiry = datetime.fromisoformat(user_data[uid]['vip_expiry'])
        if datetime.now() > expiry:
            user_data[uid]['is_vip'] = False
            user_data[uid]['vip_expiry'] = None
            save_data()
            try:
                bot.send_message(int(uid), "💔 Your VIP expired. Renew or continue with Normal access.")
            except:
                pass

    # Check Normal expiry
    if user_data[uid]['is_normal']:
        expiry = datetime.fromisoformat(user_data[uid]['normal_expiry'])
        if datetime.now() > expiry:
            user_data[uid]['is_normal'] = False
            user_data[uid]['normal_expiry'] = None
            save_data()
            try:
                bot.send_message(int(uid), "💔 Your Normal access expired. Renew to keep using the bot.")
            except:
                pass

def has_access(user_id):
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
        'entry': entry,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'confidence': int(confidence),
        'rr': f'1:{rr}',
        'is_fresh': confidence >= 85 and is_vip,
        'timestamp': datetime.now().isoformat(),
        'pair': pair
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

# ===== BOT COMMANDS =====
@bot.message_handler(commands=['start'])
def start(message):
    user_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name
    init_user(user_id, username)
    check_subscription_expiry(int(user_id))

    if user_data[user_id]['is_vip']:
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn1 = types.InlineKeyboardButton("🔥 Get Signal", callback_data="get_signal")
        btn2 = types.InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
        btn3 = types.InlineKeyboardButton("📈 Last 5 Signals", callback_data="last_signals")
        btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
        btn5 = types.InlineKeyboardButton("📞 Support", url=f"https://t.me/{SUPPORT_HANDLE}")
        markup.add(btn1, btn2, btn3, btn4, btn5)

        expiry = user_data[user_id]['vip_expiry'][:10]
        bot.send_message(message.chat.id, f"💎 *Welcome back VIP @{username}*\n\nExpires: {expiry}\nScans: Unlimited", parse_mode='Markdown', reply_markup=markup)

    elif user_data[user_id]['is_normal']:
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn1 = types.InlineKeyboardButton("🔥 Get Signal", callback_data="get_signal")
        btn2 = types.InlineKeyboardButton("💎 Upgrade VIP", callback_data="go_vip")
        btn3 = types.InlineKeyboardButton("📊 My Stats", callback_data="my_stats")
        btn4 = types.InlineKeyboardButton("📈 Last 5 Signals", callback_data="last_signals")
        btn5 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
        markup.add(btn1, btn2, btn3, btn4, btn5)

        expiry = user_data[user_id]['normal_expiry'][:10]
        scans_left = 10 - user_data[user_id]['scans_today']
        bot.send_message(message.chat.id, f"💰 *Welcome @{username}*\n\nPlan: Normal\nExpires: {expiry}\nScans left today: {scans_left}/10", parse_mode='Markdown', reply_markup=markup)

    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💰 Normal - 1000 KSH/week", callback_data="choose_normal"))
        markup.add(types.InlineKeyboardButton("💎 VIP - 2000 KSH/week", callback_data="choose_vip"))
        bot.send_message(message.chat.id, START_MSG, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['adduser'])
def cmd_adduser(message):
    print(f"=== /ADDUSER HIT BY {message.from_user.id} ===", flush=True)

    if message.from_user.id!= ADMIN_ID:
        bot.reply_to(message, "❌ Not admin")
        return

    try:
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "Usage: /adduser 8552719664 VIP")
            return

        user_id = int(parts[1]) # Force it to be a number
        tier = parts[2].upper()

        if tier not in ['VIP', 'NORMAL']:
            bot.reply_to(message, "❌ Tier must be VIP or NORMAL")
            return

        USERS_DATA[user_id] = {
            'tier': tier,
            'expiry': datetime.now(timezone.utc) + timedelta(days=7)
        }

        bot.reply_to(message, f"✅ Added {user_id} as {tier}")
        print(f"=== SAVED: {USERS_DATA} ===", flush=True)
    except ValueError:
        bot.reply_to(message, "❌ User ID must be a number. Example: /adduser 8552719664 VIP")
    except Exception as e:
        print(f"=== ADDUSER ERROR: {e} ===", flush=True)
        bot.reply_to(message, f"Error: {e}")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = str(call.from_user.id)
    check_subscription_expiry(int(user_id))
    init_user(user_id, call.from_user.username or call.from_user.first_name)

    if call.data == "choose_normal":
        bot.edit_message_text(call.message.text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif call.data == "choose_vip" or call.data == "go_vip":
        bot.edit_message_text(VIP_MSG, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif call.data == "get_signal":
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired. Renew to continue.")
            return

        today = str(datetime.now().date())
        if user_data[user_id]['last_scan_date']!= today:
            user_data[user_id]['scans_today'] = 0
            user_data[user_id]['last_scan_date'] = today
            save_data()

        is_vip = user_data[user_id]['is_vip']
        if not is_vip and user_data[user_id]['scans_today'] >= 10:
            bot.answer_callback_query(call.id, "Daily limit 10 reached. Upgrade to VIP for unlimited.")
            return

        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [types.InlineKeyboardButton(pair, callback_data=f"scan_{pair}") for pair in PAIRS]
        markup.add(*buttons)
        bot.edit_message_text("Select pair to scan:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data == "my_stats":
        is_vip = user_data[user_id]['is_vip']
        is_normal = user_data[user_id]['is_normal']
        scans = user_data[user_id]['scans_today']

        if is_vip:
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
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

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
        start(call.message)

    elif call.data.startswith("scan_"):
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired. Renew to continue.")
            return

        if is_quiet_hours(user_id):
            bot.answer_callback_query(call.id, "Quiet hours active. No signals 10PM-7AM EAT.")
            return

        pair = call.data.split("_")[1]
        is_vip = user_data[user_id]['is_vip']
        user_min_conf = user_data[user_id]['settings']['min_confidence']

        bot.answer_callback_query(call.id, f"Scanning {pair}...")
        bot.edit_message_text(f"🔍 Scanning {pair} with 10 strategies... Please wait", call.message.chat.id, call.message.message_id)

        signal = analyze_pair(pair, is_vip, user_min_conf)

        if signal:
            user_data[user_id]['scans_today'] += 1
            save_signal_to_history(user_id, signal)
            signal_text = format_signal(pair, signal, is_vip)
            bot.edit_message_text(signal_text, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        else:
            bot.edit_message_text(f"❌ No A+ setup on {pair} right now. We don't force trades.", call.message.chat.id, call.message.message_id)

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

Activate Normal: `/adduser {user_id}`
Activate VIP: `/addvip {user_id}`
"""
    try:
        bot.send_message(ADMIN_ID, alert_msg, parse_mode='Markdown')
    except:
        print(f"Failed to alert admin for {user_id}")

# ===== SCHEDULED JOBS =====
def killzone_ping():
    for uid in user_data:
        if user_data[uid]['is_vip'] and user_data[uid]['settings']['killzone_pings'] and not is_quiet_hours(uid):
            try:
                bot.send_message(int(uid), "🎯 *Killzone Active*\n\nLondon/NY session is live. Bot scanning for sniper entries...", parse_mode='Markdown')
            except:
                pass

def sunday_outlook():
    msg = "📈 *Sunday Weekly Outlook*\n\nKey levels to watch this week:\nXAUUSD: 2630 support, 2670 resistance\nEURUSD: 1.0850 key zone\n\nBot is live. Good luck this week VIP 💎"
    for uid in user_data:
        if user_data[uid]['is_vip']:
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

# ===== ADMIN COMMANDS =====
@bot.message_handler(commands=['adduser'])
def add_user(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        target_id = message.text.split()[1]
        expiry = datetime.now() + timedelta(days=7)
        if target_id not in user_data:
            init_user(target_id, 'Unknown')
        user_data[target_id]['is_normal'] = True
        user_data[target_id]['normal_expiry'] = expiry.isoformat()
        save_data()
        bot.reply_to(message, f"✅ Added Normal access to {target_id} until {expiry.date()}")
        bot.send_message(int(target_id), "💰 Normal access active! You have 10 scans/day for 7 days. Type /start")
    except:
        bot.reply_to(message, "Usage: /adduser 123456789")

@bot.message_handler(commands=['addvip'])
def add_vip(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        target_id = message.text.split()[1]
        expiry = datetime.now() + timedelta(days=7)
        if target_id not in user_data:
            init_user(target_id, 'Unknown')
        user_data[target_id]['is_vip'] = True
        user_data[target_id]['vip_expiry'] = expiry.isoformat()
        save_data()
        bot.reply_to(message, f"✅ Added VIP to {target_id} until {expiry.date()}")
        bot.send_message(int(target_id), "💎 VIP is now active! Unlimited scans + priority alerts. Type /start")
    except:
        bot.reply_to(message, "Usage: /addvip 123456789")

@bot.message_handler(commands=['removevip'])
def remove_vip(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        target_id = message.text.split()[1]
        if target_id in user_data:
            user_data[target_id]['is_vip'] = False
            user_data[target_id]['vip_expiry'] = None
            save_data()
            bot.reply_to(message, f"✅ Removed VIP from {target_id}")
            bot.send_message(int(target_id), "💔 Your VIP access has been removed.")
        else:
            bot.reply_to(message, "User not found.")
    except:
        bot.reply_to(message, "Usage: /removevip 123456789")

@bot.message_handler(commands=['removenormal'])
def remove_normal(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        target_id = message.text.split()[1]
        if target_id in user_data:
            user_data[target_id]['is_normal'] = False
            user_data[target_id]['normal_expiry'] = None
            save_data()
            bot.reply_to(message, f"✅ Removed Normal access from {target_id}")
            bot.send_message(int(target_id), "💔 Your Normal access has been removed.")
        else:
            bot.reply_to(message, "User not found.")
    except:
        bot.reply_to(message, "Usage: /removenormal 123456789")

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        msg_text = message.text.split(' ', 1)[1]
        sent = 0
        failed = 0
        for uid in user_data:
            if has_access(uid):
                try:
                    bot.send_message(int(uid), f"📢 *Announcement*\n\n{msg_text}", parse_mode='Markdown')
                    sent += 1
                    time.sleep(0.05)
                except:
                    failed += 1
        bot.reply_to(message, f"✅ Broadcast sent to {sent} active users. Failed: {failed}")
    except:
        bot.reply_to(message, "Usage: /broadcast Your message here")

@bot.message_handler(commands=['stats'])
def admin_stats(message):
    if message.from_user.id!= ADMIN_ID:
        return
    total_users = len(user_data)
    vip_users = sum(1 for u in user_data.values() if u['is_vip'])
    normal_users = sum(1 for u in user_data.values() if u['is_normal'] and not u['is_vip'])
    cache_size = len(price_cache)

    # Count today's scans + estimate API calls
    today_scans = sum(u['scans_today'] for u in user_data.values())
    estimated_calls = today_scans * 3
    usage_pct = int((estimated_calls / 800) * 100)

    # Status indicator
    if estimated_calls < 600:
        status = '🟢 Safe'
    elif estimated_calls < 750:
        status = '🟡 Warning - Approaching limit'
    else:
        status = '🔴 DANGER - Upgrade TwelveData NOW'

    msg = f"""📊 *BOT STATS - LIVE*

*Users:*
Total: {total_users}
VIP: {vip_users} 💎
Normal: {normal_users} 💰

*API Usage Today:*
Scans Run: {today_scans}
Est. Calls: ~{estimated_calls}/800 ({usage_pct}%)
Status: {status}

*Cache:*
Pairs Cached: {cache_size}/48
Efficiency: ~70%+ saved

*Revenue Potential:*
Max Safe Users: ~180
Current: {vip_users + normal_users}/180

Run `/stats` anytime to check."""
    bot.reply_to(message, msg, parse_mode='Markdown')

# ===== START BOT =====
if __name__ == "__main__":
    load_data()
    print(f"Bot online: @Denverlykbot")
    print(f"Admin: {ADMIN_ID}")
    print(f"M-Pesa: {MPESA_NUMBER}")
    print(f"2-Tier System: Normal 1000/week, VIP 2000/week")

    threading.Thread(target=run_schedule, daemon=True).start()
    bot.infinity_polling()
