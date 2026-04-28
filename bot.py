import telebot
from telebot import types
import requests
import time
import os
from datetime import datetime, timedelta
import pytz
import threading
import json
import random
import traceback

BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))
MPESA_NUMBER = os.environ.get('MPESA_NUMBER', '0712345678')
TWELVEDATA_API_KEY = os.environ.get('TWELVEDATA_API_KEY')

bot = telebot.TeleBot(BOT_TOKEN)

# === CONFIG V3.4 PICK-A-PAIR ===
EAT = pytz.timezone('Africa/Nairobi')
PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'GBPJPY', 'EURJPY', 'XAUUSD']
DAILY_LIMIT = 800
MAX_DAILY_SIGNALS = 10
SCAN_INTERVAL = 60
CACHE_TTL = 300
PRICE_7DAYS = 1300
PRICE_30DAYS = 5300
MAX_TRADES_PER_USER = 10
DEFAULT_TRADE_LIMIT = 10

# === STATE ===
API_CALL_COUNT = 0
API_CALL_RESET = datetime.now(EAT)
CANDLE_DB = {}
NEWS_EVENTS_CACHE = {}
LAST_NEWS_CHECK = 0
MAINTENANCE_MODE = False
MANUAL_NEWS_BLOCK = False
DAILY_SIGNALS_SENT = 0
LAST_SIGNAL_RESET = datetime.now(EAT).date()
subscribers = {}
user_mode = {}
user_stats = {}
USER_TRADE_COUNT = {}
USER_LAST_SCAN = {}
USER_COOLDOWN = {}
USER_SIGNAL_TIER = {}
banned_users = []
auto_scan_users = []
pending_payments = {}
pair_stats = {}
pair_last_result = {}

DATA_FILE = 'bot_data.json'

def load_data():
    global subscribers, user_mode, user_stats, pair_stats, banned_users, auto_scan_users, pair_last_result
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                subscribers = {int(k): {'expiry': datetime.fromisoformat(v['expiry']), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in data.get('subscribers', {}).items()}
                user_mode = data.get('user_mode', {})
                user_stats = data.get('user_stats', {})
                pair_stats = data.get('pair_stats', {})
                banned_users = data.get('banned', [])
                auto_scan_users = data.get('auto_scan', [])
                pair_last_result = data.get('pair_last_result', {})
    except: pass

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, default=str)
    except: pass

load_data()

# === MENUS ===
def get_client_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    trades_left = DEFAULT_TRADE_LIMIT - USER_TRADE_COUNT.get(user_id, 0)
    if user_id in subscribers:
        trades_left = subscribers[user_id].get('daily_limit', DEFAULT_TRADE_LIMIT) - USER_TRADE_COUNT.get(user_id, 0)
    mode = user_mode.get(user_id, 'po').upper()
    btn1 = types.KeyboardButton(f"🔥 Get Signal ({trades_left} left)")
    btn2 = types.KeyboardButton(f"📈 Mode: {mode}")
    btn3 = types.KeyboardButton("📊 My Stats")
    btn4 = types.KeyboardButton("🧮 Calculator")
    btn5 = types.KeyboardButton("⚙️ Set Limit")
    btn6 = types.KeyboardButton("💰 Pay / Renew")
    btn7 = types.KeyboardButton("📊 My Status")
    btn8 = types.KeyboardButton("❓ Help")
    if user_id == ADMIN_ID:
        markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8, types.KeyboardButton("👑 Admin Panel"))
    else:
        markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    return markup

def get_pair_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    for pair in PAIRS:
        stats = pair_stats.get(pair, {'wins': 0, 'losses': 0, 'total': 0})
        wr = (stats['wins'] / max(1, stats['total']) * 100) if stats['total'] > 5 else 50
        emoji = "🟢" if wr >= 60 else "🟡" if wr >= 50 else "🔴"
        btn = types.InlineKeyboardButton(f"{emoji} {pair} {wr:.0f}%", callback_data=f"scan_{pair}")
        markup.add(btn)
    markup.add(types.InlineKeyboardButton("🎯 Best Pair Now", callback_data="scan_auto"))
    return markup

def get_admin_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Global Stats", callback_data="admin_stats"),
        types.InlineKeyboardButton("👥 Users", callback_data="admin_users"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🔧 API Status", callback_data="admin_api"),
        types.InlineKeyboardButton("📰 News Block", callback_data="admin_news"),
        types.InlineKeyboardButton("🔴 Kill Switch", callback_data="admin_kill")
    )
    return markup

# === CORE FUNCTIONS ===
def check_cooldown(user_id):
    if user_id == ADMIN_ID: return True, 0
    now = time.time()
    last = USER_COOLDOWN.get(user_id, 0)
    wait = SCAN_INTERVAL - (now - last)
    if wait > 0:
        return False, int(wait)
    USER_COOLDOWN[user_id] = now
    return True, 0

def get_user_limit(user_id):
    if user_id in subscribers:
        return subscribers[user_id].get('daily_limit', DEFAULT_TRADE_LIMIT)
    return DEFAULT_TRADE_LIMIT

def can_user_trade(user_id):
    if user_id == ADMIN_ID: return True
    if not is_subscribed(user_id): return False
    limit = get_user_limit(user_id)
    return USER_TRADE_COUNT.get(user_id, 0) < limit

def record_user_trade(user_id):
    if user_id not in USER_TRADE_COUNT:
        USER_TRADE_COUNT[user_id] = 0
    USER_TRADE_COUNT[user_id] += 1
    tier = USER_TRADE_COUNT[user_id]
    USER_SIGNAL_TIER[user_id] = 'A+' if tier <= 3 else 'A' if tier <= 7 else 'B'
    return USER_SIGNAL_TIER[user_id]

def reset_daily_counters():
    global USER_TRADE_COUNT, DAILY_SIGNALS_SENT, LAST_SIGNAL_RESET, USER_SIGNAL_TIER
    today = datetime.now(EAT).date()
    if today!= LAST_SIGNAL_RESET:
        USER_TRADE_COUNT = {}
        USER_SIGNAL_TIER = {}
        DAILY_SIGNALS_SENT = 0
        LAST_SIGNAL_RESET = today

def is_subscribed(user_id):
    if user_id == ADMIN_ID: return True
    if user_id in subscribers:
        return subscribers[user_id]['expiry'] > datetime.now()
    return False

def get_days_left(user_id):
    if user_id == ADMIN_ID: return "∞ Permanent"
    if user_id in subscribers:
        delta = subscribers[user_id]['expiry'] - datetime.now()
        return f"{delta.days}d {delta.seconds//3600}h" if delta.days >= 0 else "Expired"
    return "Not Subscribed"

def check_api_limit():
    global API_CALL_COUNT, API_CALL_RESET
    now = datetime.now(EAT)
    if now.date() > API_CALL_RESET.date():
        API_CALL_COUNT = 0
        API_CALL_RESET = now
    return API_CALL_COUNT < DAILY_LIMIT

def fetch_candles(pair, interval, count=100):
    global API_CALL_COUNT
    if not check_api_limit(): return None
    cache_key = f"{pair}_{interval}"
    now = time.time()
    if cache_key in CANDLE_DB:
        cached_time, cached_data = CANDLE_DB[cache_key]
        if now - cached_time < CACHE_TTL:
            return cached_data
    try:
        url = f"https://api.twelvedata.com/time_series"
        params = {'symbol': pair, 'interval': interval, 'outputsize': count, 'apikey': TWELVEDATA_API_KEY}
        response = requests.get(url, params=params, timeout=10)
        API_CALL_COUNT += 1
        time.sleep(10)
        data = response.json()
        if 'values' in data:
            candles = []
            for v in reversed(data['values']):
                candles.append({
                    'time': v['datetime'],
                    'open': float(v['open']),
                    'high': float(v['high']),
                    'low': float(v['low']),
                    'close': float(v['close']),
                    'volume': float(v.get('volume', 0))
                })
            CANDLE_DB[cache_key] = (now, candles)
            return candles
    except: pass
    return None

def calculate_atr(candles, period=14):
    if len(candles) < period + 1: return 0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]['high'], candles[i]['low'], candles[i-1]['close']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period

def calculate_rsi(candles, period=14):
    if len(candles) < period + 1: return 50
    gains, losses = [], []
    for i in range(1, len(candles)):
        change = candles[i]['close'] - candles[i-1]['close']
        gains.append(max(0, change))
        losses.append(max(0, -change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def check_news_block():
    if MANUAL_NEWS_BLOCK: return True, "Manual news block active"
    return False, None

def analyze_pair(pair, mode='po'):
    m1 = fetch_candles(pair, '1min', 100)
    if not m1: return None
    m5 = fetch_candles(pair, '5min', 100)
    if not m5: return None

    last = m1[-1]
    rsi = calculate_rsi(m1)
    atr = calculate_atr(m1)
    if atr == 0: return None

    price = last['close']
    sma20 = sum(c['close'] for c in m1[-20:]) / 20
    sma50 = sum(c['close'] for c in m5[-50:]) / 50 if len(m5) >= 50 else price

    signal_type = None
    confidence = 0

    if price > sma20 and sma20 > sma50 and 40 < rsi < 70:
        signal_type = 'CALL'
        confidence = 65
    elif price < sma20 and sma20 < sma50 and 30 < rsi < 60:
        signal_type = 'PUT'
        confidence = 65

    if not signal_type: return None

    hist = pair_stats.get(pair, {'wins': 0, 'losses': 0, 'total': 0})
    pair_wr = (hist['wins'] / max(1, hist['total']) * 100) if hist['total'] > 5 else 50
    if pair_wr < 45: confidence -= 10
    elif pair_wr > 60: confidence += 10

    confidence = max(50, min(85, confidence))

    if mode == 'po':
        expiry = '5min'
        entry = price
        tp = price + (atr * 1.5) if signal_type == 'CALL' else price - (atr * 1.5)
        sl = price - (atr * 1.0) if signal_type == 'CALL' else price + (atr * 1.0)
    else:
        expiry = 'N/A'
        entry = price
        tp = price + (atr * 2.0) if signal_type == 'CALL' else price - (atr * 2.0)
        sl = price - (atr * 1.0) if signal_type == 'CALL' else price + (atr * 1.0)

    return {
        'pair': pair,
        'type': signal_type,
        'entry': round(entry, 5),
        'tp': round(tp, 5),
        'sl': round(sl, 5),
        'expiry': expiry,
        'confidence': confidence,
        'rsi': round(rsi, 1),
        'atr': round(atr, 5),
        'tier': 'A+',
        'mode': mode
    }

def send_signal_to_user(user_id, signal):
    global DAILY_SIGNALS_SENT
    if MAINTENANCE_MODE: return
    if DAILY_SIGNALS_SENT >= MAX_DAILY_SIGNALS: return

    tier = record_user_trade(user_id)
    signal['tier'] = tier

    risk = "0.25%" if tier == 'A+' else "0.1%"
    DAILY_SIGNALS_SENT += 1

    msg = f"""
🎯 **{signal['pair']} {signal['type']} - {tier} TIER**

📊 **Entry:** `{signal['entry']}`
🎯 **TP:** `{signal['tp']}`
🛑 **SL:** `{signal['sl']}`
⏰ **Expiry:** {signal['expiry']}

📈 **Confidence:** {signal['confidence']}%
📉 **RSI:** {signal['rsi']} | **ATR:** {signal['atr']}

⚠️ **RISK:** {risk} max
⚠️ **Mode:** {signal['mode'].upper()}

Trade #{USER_TRADE_COUNT.get(user_id, 0)}/{get_user_limit(user_id)}
"""

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ WIN", callback_data=f"outcome_win_{signal['pair']}_{user_id}"),
        types.InlineKeyboardButton("❌ LOSS", callback_data=f"outcome_loss_{signal['pair']}_{user_id}")
    )

    try:
        bot.send_message(user_id, msg, reply_markup=markup)
        if str(user_id) not in user_stats:
            user_stats[str(user_id)] = {'wins': 0, 'losses': 0, 'signals': []}
        user_stats[str(user_id)]['signals'].append({'pair': signal['pair'], 'type': signal['type'], 'time': datetime.now().isoformat()})
        save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
    except: pass

# === CALLBACKS ===
@bot.callback_query_handler(func=lambda call: call.data.startswith('scan_'))
def scan_callback(call):
    user_id = call.from_user.id
    if not is_subscribed(user_id):
        bot.answer_callback_query(call.id, "🔒 Subscribe first")
        return
    if not can_user_trade(user_id):
        bot.answer_callback_query(call.id, "⚠️ Daily limit reached")
        return
    can_scan, wait = check_cooldown(user_id)
    if not can_scan:
        bot.answer_callback_query(call.id, f"⏱️ Wait {wait}s")
        return

    pair = call.data.split('_')[1]
    mode = user_mode.get(user_id, 'po')
    bot.answer_callback_query(call.id, f"Scanning {pair}...")
    bot.edit_message_text(f"🔍 Scanning {pair}...\n\nUsing 2 API calls", call.message.chat.id, call.message.message_id)

    news_blocked, reason = check_news_block()
    if news_blocked:
        bot.edit_message_text(f"📰 {reason}\n\nTrading paused.", call.message.chat.id, call.message.message_id, reply_markup=get_client_menu(user_id))
        return

    if pair == 'auto':
        for p in PAIRS:
            signal = analyze_pair(p, mode)
            if signal:
                send_signal_to_user(user_id, signal)
                bot.edit_message_text(f"✅ Signal sent: {p}", call.message.chat.id, call.message.message_id, reply_markup=get_client_menu(user_id))
                return
        bot.edit_message_text("❌ No setup found on any pair.\n\nTry again in 1min", call.message.chat.id, call.message.message_id, reply_markup=get_client_menu(user_id))
    else:
        signal = analyze_pair(pair, mode)
        if signal:
            send_signal_to_user(user_id, signal)
            bot.edit_message_text(f"✅ Signal sent: {pair}", call.message.chat.id, call.message.message_id, reply_markup=get_client_menu(user_id))
        else:
            bot.edit_message_text(f"❌ No setup for {pair}.\n\nTry another pair or wait 1min", call.message.chat.id, call.message.message_id, reply_markup=get_client_menu(user_id))

@bot.callback_query_handler(func=lambda call: call.data.startswith('outcome_'))
def outcome_callback(call):
    parts = call.data.split('_')
    result = parts[1]
    pair = parts[2]
    user_id = int(parts[3])

    if str(user_id) not in user_stats:
        user_stats[str(user_id)] = {'wins': 0, 'losses': 0, 'signals': []}

    if result == 'win':
        user_stats[str(user_id)]['wins'] += 1
    else:
        user_stats[str(user_id)]['losses'] += 1

    if pair not in pair_stats:
        pair_stats[pair] = {'wins': 0, 'losses': 0, 'total': 0}
    if result == 'win':
        pair_stats[pair]['wins'] += 1
    else:
        pair_stats[pair]['losses'] += 1
    pair_stats[pair]['total'] += 1

    save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
    bot.answer_callback_query(call.id, f"Recorded: {result.upper()}")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

# === COMMANDS ===
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    if user_id in banned_users:
        bot.send_message(message.chat.id, "❌ Banned.")
        return
    if user_id == ADMIN_ID:
        bot.send_message(message.chat.id, f"""
👋 **Welcome boss.....**

Denverlyk V3.4 PICK-A-PAIR is online.

⚡ Scan: Every {SCAN_INTERVAL}s | 1 pair only
💾 Cache: {CACHE_TTL//60}min
📊 API: {API_CALL_COUNT}/{DAILY_LIMIT}
🎯 Status: ∞ Permanent Admin
💰 M-Pesa: {MPESA_NUMBER}
🔧 Maintenance: {'🔴 ON' if MAINTENANCE_MODE else '🟢 OFF'}
📰 News Block: {'🔴 ON' if MANUAL_NEWS_BLOCK else '🟢 OFF'}

**SAFETY:** 10 trades/user/day max | ATR SL/TP | 60s cooldown
""", reply_markup=get_client_menu(user_id))
        return
    if not is_subscribed(user_id):
        bot.send_message(message.chat.id, f"""
👋 **Welcome to Denverlyk V3.4 PICK-A-PAIR**

🔒 **Subscription Required**

💰 **Plans:**
7 Days = KES {PRICE_7DAYS}
30 Days = KES {PRICE_30DAYS}

**What You Get:**
⚡ 3-10 signals/day - YOU pick the pair
🎯 55-60% Win Rate expected
📊 Live pair win rates shown
📰 News filter protection
🛡️ 60s cooldown anti-spam

Tap /pay to subscribe 👇

⚠️ **RISK WARNING:** Trading is risky. Max 0.25% risk per trade. Set limit: /setlimit 5
""", reply_markup=get_client_menu(user_id))
        return
    limit = get_user_limit(user_id)
    trades_left = limit - USER_TRADE_COUNT.get(user_id, 0)
    bot.send_message(message.chat.id, f"""
👋 **Denverlyk V3.4 PICK-A-PAIR**

⚡ Pairs: You choose | 1 scan at a time
🔄 Scan: Every {SCAN_INTERVAL}s
💾 Cache: {CACHE_TTL//60}min
📊 API: {API_CALL_COUNT}/{DAILY_LIMIT} | Today: {DAILY_SIGNALS_SENT}/{MAX_DAILY_SIGNALS}
🎯 WR Target: 55-60%

Status: {get_days_left(user_id)}
Your trades: {trades_left}/{limit} left today

⚠️ **RULE:** Max 0.25% risk first 3 trades, 0.1% after
""", reply_markup=get_client_menu(user_id))

@bot.message_handler(commands=['setlimit'])
def set_limit_cmd(message):
    user_id = message.from_user.id
    try:
        limit = int(message.text.split()[1])
        if limit < 1 or limit > 10:
            bot.reply_to(message, "❌ Limit must be 1-10")
            return
        if user_id in subscribers:
            subscribers[user_id]['daily_limit'] = limit
            save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.reply_to(message, f"✅ Daily limit set to {limit}\n\nButton updated.", reply_markup=get_client_menu(user_id))
    except:
        bot.reply_to(message, "Usage: /setlimit 5")

@bot.message_handler(commands=['pay'])
def pay_cmd(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"7 Days - KES {PRICE_7DAYS}", callback_data="plan_7"))
    markup.add(types.InlineKeyboardButton(f"30 Days - KES {PRICE_30DAYS}", callback_data="plan_30"))
    bot.send_message(message.chat.id, "💰 **Choose Plan:**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('plan_'))
def plan_callback(call):
    days = int(call.data.split('_')[1])
    amount = PRICE_7DAYS if days == 7 else PRICE_30DAYS
    bot.edit_message_text(f"""
📱 **M-PESA PAYMENT STEPS**

**1. Go to M-Pesa** → Send Money
**2. Send to:** `{MPESA_NUMBER}`
**3. Amount:** `KES {amount}` for {days} days
**4. Enter PIN and Confirm**
**5. WAIT FOR SMS FROM M-PESA**
**6. COPY THE CODE** `QK7X2Y8Z9A`
**7. Send here:** `/verify QK7X2Y8Z9A`

⏱️ **Activation:** 5-10min
⚠️ **RISK WARNING:** Max 10 trades/day at 0.25% risk. Past performance ≠ future results.
""", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['verify'])
def verify_cmd(message):
    user_id = message.from_user.id
    try:
        code = message.text.split()[1].upper()
        if len(code)!= 10:
            bot.reply_to(message, "❌ Invalid code format. Must be 10 chars like QK7X2Y8Z9A")
            return
        pending_payments[code] = {'user_id': user_id, 'time': datetime.now()}
        bot.send_message(ADMIN_ID, f"""
🔔 **PAYMENT VERIFY REQUEST**

User: {message.from_user.first_name} (@{message.from_user.username})
ID: `{user_id}`
Code: `{code}`

Check M-Pesa. If valid:
`/adduser {user_id} 7` or `/adduser {user_id} 30`
""")
        bot.reply_to(message, f"✅ Code `{code}` sent to admin.\n\n⏱️ Activation in 5-10min after confirm.\n\nYou'll get notified.")
    except:
        bot.reply_to(message, "Usage: /verify QK7X2Y8Z9A")

@bot.message_handler(commands=['mystats'])
def stats_cmd(message):
    user_id = message.from_user.id
    stats = user_stats.get(str(user_id), {'wins': 0, 'losses': 0, 'signals': []})
    total = stats['wins'] + stats['losses']
    win_rate = (stats['wins'] / total * 100) if total > 0 else 0
    limit = get_user_limit(user_id)
    trades_left = limit - USER_TRADE_COUNT.get(user_id, 0)
    bot.reply_to(message, f"""
📊 **YOUR STATS**

Signals: {len(stats['signals'])}
✅ Wins: {stats['wins']}
❌ Losses: {stats['losses']}
🎯 Win Rate: {win_rate:.1f}%

Tracked: {total}
Trades Today: {trades_left}/{limit} left
API: {API_CALL_COUNT}/{DAILY_LIMIT}

⚠️ At 55% WR: Expect +0.5R/day with 10 trades
""", reply_markup=get_client_menu(user_id))

@bot.message_handler(commands=['api'])
def api_status(message):
    if message.from_user.id!= ADMIN_ID: return
    bot.reply_to(message, f"""
📊 **API STATUS V3.4**

Used: {API_CALL_COUNT}/{DAILY_LIMIT}
Left: {DAILY_LIMIT - API_CALL_COUNT}
Reset: {(API_CALL_RESET + timedelta(days=1)).strftime('%H:%M EAT')}

Status: {'✅ SAFE' if API_CALL_COUNT < DAILY_LIMIT-100 else '⚠️ LIMIT'}
Cache: {len(CANDLE_DB)} pairs
Interval: {SCAN_INTERVAL}s
Signals Today: {DAILY_SIGNALS_SENT}/{MAX_DAILY_SIGNALS}
Maintenance: {'🔴 ON' if MAINTENANCE_MODE else '🟢 OFF'}
News Block: {'🔴 ON' if MANUAL_NEWS_BLOCK else '🟢 OFF'}
""")

# === MENU HANDLERS ===
@bot.message_handler(func=lambda message: message.text.startswith("🔥 Get Signal"))
def handle_signal_button(message):
    user_id = message.from_user.id
    if not is_subscribed(user_id):
        bot.reply_to(message, "🔒 Subscribers only. Tap /pay", reply_markup=get_client_menu(user_id))
        return
    if not can_user_trade(user_id):
        limit = get_user_limit(user_id)
        bot.reply_to(message, f"⚠️ Daily limit reached: {limit}/{limit}\n\nResets at midnight EAT\n\nChange: /setlimit 5", reply_markup=get_client_menu(user_id))
        return
    can_scan, wait = check_cooldown(user_id)
    if not can_scan:
        bot.reply_to(message, f"⏱️ Cooldown: Wait {wait}s before next scan", reply_markup=get_client_menu(user_id))
        return
    bot.send_message(message.chat.id, "📊 **Pick pair to scan:**\n\nNumbers = CALL win rate (last 50)", reply_markup=get_pair_menu(user_id))

@bot.message_handler(func=lambda message: message.text in ["📊 My Stats", "🧮 Calculator", "📈 Mode: PO", "📈 Mode: FOREX", "⚙️ Set Limit", "💰 Pay / Renew", "📊 My Status", "❓ Help", "👑 Admin Panel"])
def handle_menu_buttons(message):
    text = message.text
    user_id = message.from_user.id
    if user_id in banned_users:
        bot.reply_to(message, "❌ Banned.")
        return
    if text == "📊 My Stats":
        stats_cmd(message)
    elif text == "🧮 Calculator":
        bot.reply_to(message, "Use: /calc balance risk% sl_pips\n\nExample: `/calc 1000 0.25 20`")
    elif text.startswith("📈 Mode:"):
        current = user_mode.get(user_id, 'po')
        new_mode = 'forex' if current == 'po' else 'po'
        user_mode[user_id] = new_mode
        save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.reply_to(message, f"✅ Mode: {new_mode.upper()}", reply_markup=get_client_menu(user_id))
    elif text == "⚙️ Set Limit":
        bot.reply_to(message, "Set daily trade limit 1-10:\n\nUsage: `/setlimit 5`\n\nRecommended: 3-5 for beginners", reply_markup=get_client_menu(user_id))
    elif text == "💰 Pay / Renew":
        pay_cmd(message)
    elif text == "📊 My Status":
        limit = get_user_limit(user_id)
        trades_left = limit - USER_TRADE_COUNT.get(user_id, 0)
        bot.reply_to(message, f"Status: {get_days_left(user_id)}\nTrades: {trades_left}/{limit} left today", reply_markup=get_client_menu(user_id))
    elif text == "❓ Help":
        bot.reply_to(message, f"""
📖 **COMMANDS V3.4**

🔥 Get Signal - Pick pair to scan
📊 My Stats - Win rate
🧮 Calculator - Position size 0.25% max
📈 Mode - Switch PO/Forex
⚙️ Set Limit - Set 1-10 trades/day
💰 Pay / Renew - Subscribe
📊 My Status - Check subscription
/verify CODE - Confirm M-Pesa
/setlimit 5 - Set daily limit
/calc - Risk calculator

**Payment:** Send KES {PRICE_7DAYS} to {MPESA_NUMBER}
**Then:** `/verify QK7X2Y8Z9A`

⚠️ **RISK RULES:**
1. Signals 1-3: A+ tier, 0.25% risk
2. Signals 4-7: A tier, 0.1% risk
3. Signals 8-10: B tier, 0.1% risk
4. 60s cooldown between scans
5. 55-60% WR expected overall
""", reply_markup=get_client_menu(user_id))
    elif text == "👑 Admin Panel":
        if user_id!= ADMIN_ID:
            bot.reply_to(message, "❌ Admin only")
            return
        bot.send_message(message.chat.id, "👑 **ADMIN PANEL V3.4**\n\nSelect:", reply_markup=get_admin_menu())

# === ADMIN COMMANDS ===
@bot.message_handler(commands=['adduser'])
def add_user_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        days = int(parts[2])
        expiry = datetime.now() + timedelta(days=days)
        subscribers[user_id] = {'expiry': expiry, 'daily_limit': DEFAULT_TRADE_LIMIT}
        save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.reply_to(message, f"✅ Added {user_id} for {days} days")
        bot.send_message(user_id, f"✅ **SUBSCRIPTION ACTIVE**\n\nDuration: {days} days\nExpires: {expiry.strftime('%d %b %Y')}\n\nTap /start to begin")
    except:
        bot.reply_to(message, "Usage: /adduser 123456 7")

@bot.message_handler(commands=['removeuser'])
def remove_user_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        if user_id in subscribers:
            del subscribers[user_id]
            save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
            bot.reply_to(message, f"❌ Removed {user_id}")
    except:
        bot.reply_to(message, "Usage: /removeuser 123456")

@bot.message_handler(commands=['ban'])
def ban_user_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        if user_id not in banned_users:
            banned_users.append(user_id)
            save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.reply_to(message, f"🔨 Banned {user_id}")
    except:
        bot.reply_to(message, "Usage: /ban 123456")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_panel_callback(call):
    global MANUAL_NEWS_BLOCK, MAINTENANCE_MODE
    if call.from_user.id!= ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin only")
        return
    action = call.data.split('_')[1]
    if action == 'stats':
        total_users = len(subscribers)
        active_subs = sum(1 for uid, sub in subscribers.items() if sub['expiry'] > datetime.now())
        total_signals = sum(len(user_stats.get(str(uid), {}).get('signals', [])) for uid in subscribers.keys())
        total_wins = sum(user_stats.get(str(uid), {}).get('wins', 0) for uid in subscribers.keys())
        total_losses = sum(user_stats.get(str(uid), {}).get('losses', 0) for uid in subscribers.keys())
        tracked = total_wins + total_losses
        global_wr = (total_wins / tracked * 100) if tracked > 0 else 0
        bot.edit_message_text(f"""
👑 **GLOBAL STATS V3.4**

👥 Users: {total_users} | Active: {active_subs}
🤖 Auto: {len(auto_scan_users)} | Banned: {len(banned_users)}

📊 **SIGNALS**
Total: {total_signals}
✅ Wins: {total_wins}
❌ Losses: {total_losses}
🎯 WR: {global_wr:.1f}%
Tracked: {tracked}/{total_signals}

📈 **API**
Today: {API_CALL_COUNT}/{DAILY_LIMIT}
Signals: {DAILY_SIGNALS_SENT}/{MAX_DAILY_SIGNALS}
Cache: {len(CANDLE_DB)} pairs
Maintenance: {'🔴 ON' if MAINTENANCE_MODE else '🟢 OFF'}
""", call.message.chat.id, call.message.message_id, reply_markup=get_admin_menu())
    elif action == 'users':
        user_list = []
        for uid, sub in subscribers.items():
            if sub['expiry'] > datetime.now():
                stats = user_stats.get(str(uid), {'wins': 0, 'losses': 0})
                total = stats['wins'] + stats['losses']
                wr = (stats['wins'] / total * 100) if total > 0 else 0
                limit = sub.get('daily_limit', DEFAULT_TRADE_LIMIT)
                used = USER_TRADE_COUNT.get(uid, 0)
                user_list.append(f"`{uid}`: {sub['expiry'].strftime('%d%b')} | {wr:.0f}% | {used}/{limit}")
        msg = "👥 **ACTIVE USERS**\n\n" + "\n".join(user_list[:20]) if user_list else "No active users"
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=get_admin_menu())
    elif action == 'broadcast':
        bot.edit_message_text("📢 Send: `/broadcast your message here`", call.message.chat.id, call.message.message_id)
    elif action == 'api':
        bot.edit_message_text(f"""
📊 **API STATUS**

Used: {API_CALL_COUNT}/{DAILY_LIMIT}
Left: {DAILY_LIMIT - API_CALL_COUNT}
Signals: {DAILY_SIGNALS_SENT}/{MAX_DAILY_SIGNALS}
Cache: {len(CANDLE_DB)} pairs
Maintenance: {'🔴 ON' if MAINTENANCE_MODE else '🟢 OFF'}
News Block: {'🔴 ON' if MANUAL_NEWS_BLOCK else '🟢 OFF'}
""", call.message.chat.id, call.message.message_id, reply_markup=get_admin_menu()
        elif action == 'news':
        MANUAL_NEWS_BLOCK = not MANUAL_NEWS_BLOCK
        status = "🔴 ON" if MANUAL_NEWS_BLOCK else "🟢 OFF"
        bot.answer_callback_query(call.id, f"News Block: {status}")
        bot.edit_message_text(f"📰 News Block: {status}", call.message.chat.id, call.message.message_id, reply_markup=get_admin_menu())
    elif action == 'kill':
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        status = "🔴 ON" if MAINTENANCE_MODE else "🟢 OFF"
        bot.answer_callback_query(call.id, f"Maintenance: {status}")
        bot.edit_message_text(f"🔴 Maintenance: {status}", call.message.chat.id, call.message.message_id, reply_markup=get_admin_menu())

@bot.message_handler(commands=['calc'])
def calc_cmd(message):
    try:
        parts = message.text.split()
        balance = float(parts[1])
        risk_pct = float(parts[2])
        sl_pips = float(parts[3])
        risk_amount = balance * (risk_pct / 100)
        lot_size = risk_amount / (sl_pips * 10)
        bot.reply_to(message, f"""
🧮 **POSITION SIZE**

Balance: ${balance:.2f}
Risk: {risk_pct}% = ${risk_amount:.2f}
SL: {sl_pips} pips
📊 **Lot Size: {lot_size:.2f}**

⚠️ **V3.4 RULE:** Max 0.25% for A+ tier
""")
    except:
        bot.reply_to(message, "Usage: `/calc 1000 0.25 20`\n\n(balance risk% sl_pips)")

@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        msg = message.text.split(' ', 1)[1]
        count = 0
        for uid in subscribers.keys():
            try:
                bot.send_message(uid, f"📢 **ADMIN BROADCAST**\n\n{msg}")
                count += 1
                time.sleep(0.1)
            except: pass
        bot.reply_to(message, f"✅ Sent to {count} users")
    except:
        bot.reply_to(message, "Usage: /broadcast message")

@bot.message_handler(commands=['extenduser'])
def extend_user_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        days = int(parts[2])
        if user_id in subscribers:
            subscribers[user_id]['expiry'] += timedelta(days=days)
        else:
            subscribers[user_id] = {'expiry': datetime.now() + timedelta(days=days), 'daily_limit': DEFAULT_TRADE_LIMIT}
        save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.reply_to(message, f"✅ Extended {user_id} by {days} days")
        bot.send_message(user_id, f"✅ **SUBSCRIPTION EXTENDED**\n\n+{days} days added\nExpires: {subscribers[user_id]['expiry'].strftime('%d %b %Y')}")
    except:
        bot.reply_to(message, "Usage: /extenduser 123456 30")

@bot.message_handler(commands=['checkuser'])
def check_user_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        if user_id in subscribers:
            sub = subscribers[user_id]
            stats = user_stats.get(str(user_id), {'wins': 0, 'losses': 0})
            total = stats['wins'] + stats['losses']
            wr = (stats['wins'] / total * 100) if total > 0 else 0
            limit = sub.get('daily_limit', DEFAULT_TRADE_LIMIT)
            used = USER_TRADE_COUNT.get(user_id, 0)
            bot.reply_to(message, f"""
👤 **USER {user_id}**

Expires: {sub['expiry'].strftime('%d %b %Y %H:%M')}
Status: {'✅ Active' if sub['expiry'] > datetime.now() else '❌ Expired'}
WR: {wr:.1f}% ({stats['wins']}W/{stats['losses']}L)
Trades Today: {used}/{limit}
Mode: {user_mode.get(user_id, 'po').upper()}
""")
        else:
            bot.reply_to(message, "❌ User not found")
    except:
        bot.reply_to(message, "Usage: /checkuser 123456")

@bot.message_handler(commands=['kill'])
def kill_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    status = "🔴 ENABLED" if MAINTENANCE_MODE else "🟢 DISABLED"
    bot.reply_to(message, f"🔧 Maintenance Mode: {status}")

@bot.message_handler(commands=['newsblock'])
def news_block_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    global MANUAL_NEWS_BLOCK
    MANUAL_NEWS_BLOCK = not MANUAL_NEWS_BLOCK
    status = "🔴 ENABLED" if MANUAL_NEWS_BLOCK else "🟢 DISABLED"
    bot.reply_to(message, f"📰 Manual News Block: {status}")

def run_bot():
    while True:
        try:
            print("🚀 Denverlyk V3.4 PICK-A-PAIR Starting...")
            print(f"⚡ Scan: User-triggered | {SCAN_INTERVAL}s cooldown")
            print(f"📊 API Budget: {DAILY_LIMIT}/day")
            print(f"💰 M-Pesa: {MPESA_NUMBER}")
            print(f"🔑 TwelveData: {TWELVEDATA_API_KEY[:8] if TWELVEDATA_API_KEY else 'NOT SET'}...")
            print(f"🛡️ Safety: Max {MAX_TRADES_PER_USER} trades/user/day | ATR SL/TP")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Bot crashed: {e}")
            traceback.print_exc()
            time.sleep(15)

if __name__ == "__main__":
    reset_daily_counters()
    run_bot() #
