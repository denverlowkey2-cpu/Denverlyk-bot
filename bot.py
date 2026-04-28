import telebot
from telebot import types
import requests
import json
import os
from datetime import datetime, timedelta
import threading
import time
import random
import traceback

# === CONFIG ===
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '1234567890'))
TWELVE_API_KEY = os.getenv('TWELVEDATA_API_KEY')
CASH_IN_ID = os.getenv('MPESA_NUMBER', '0712345678')

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# === STORAGE ===
subscribers = {}
user_mode = {}
user_stats = {}
pair_stats = {}
banned_users = []
auto_scan_users = []
pair_last_result = {}
CANDLE_DB = {}
USER_TRADE_COUNT = {}
DAILY_SIGNALS_SENT = 0
LAST_TRADE_TIME = {}
API_CALL_COUNT = 0
API_CALL_RESET = datetime.now()
MANUAL_NEWS_BLOCK = False
MAINTENANCE_MODE = False

# === SAFETY CONSTANTS ===
MAX_DAILY_SIGNALS = 10
DEFAULT_TRADE_LIMIT = 10
DAILY_LIMIT = 800
SCAN_INTERVAL = 60
MIN_CONFIDENCE = 65

# === PAIRS ===
PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'GBPJPY', 'EURJPY', 'XAUUSD']

# === TIMEZONE ===
EAT = 3

def is_trading_hours():
    now = datetime.utcnow() + timedelta(hours=EAT)
    return 6 <= now.hour <= 22

def reset_daily_counters():
    global API_CALL_COUNT, API_CALL_RESET, DAILY_SIGNALS_SENT, USER_TRADE_COUNT
    if datetime.now() >= API_CALL_RESET + timedelta(days=1):
        API_CALL_COUNT = 0
        API_CALL_RESET = datetime.now()
        DAILY_SIGNALS_SENT = 0
        USER_TRADE_COUNT = {}

def save_data(data):
    try:
        with open('bot_data.json', 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Save error: {e}")

def load_data():
    global subscribers, user_mode, user_stats, pair_stats, banned_users, auto_scan_users, pair_last_result
    try:
        if os.path.exists('bot_data.json'):
            with open('bot_data.json', 'r') as f:
                data = json.load(f)
                subscribers = {int(k): {'expiry': datetime.fromisoformat(v['expiry']), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in data.get('subscribers', {}).items()}
                user_mode = {int(k): v for k, v in data.get('user_mode', {}).items()}
                user_stats = data.get('user_stats', {})
                pair_stats = data.get('pair_stats', {})
                banned_users = data.get('banned', [])
                auto_scan_users = data.get('auto_scan', [])
                pair_last_result = data.get('pair_last_result', {})
    except Exception as e:
        print(f"Load error: {e}")

load_data()

def safe_edit(chat_id, message_id, text, reply_markup=None):
    try:
        bot.edit_message_text(text, chat_id, message_id, parse_mode='Markdown', reply_markup=reply_markup)
    except:
        try:
            bot.delete_message(chat_id, message_id)
        except:
            pass
        bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=reply_markup)

def get_main_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    mode = user_mode.get(user_id, 'po')
    mode_text = "📈 Mode: PO" if mode == 'po' else "📊 Mode: FOREX"
    auto_text = "🤖 Auto: ON" if user_id in auto_scan_users else "🤖 Auto: OFF"
    limit = subscribers.get(user_id, {}).get('daily_limit', DEFAULT_TRADE_LIMIT)
    used = USER_TRADE_COUNT.get(user_id, 0)
    signal_btn = types.InlineKeyboardButton(f"🔥 Get Signal ({limit-used} left)", callback_data="get_signal")
    markup.add(signal_btn)
    markup.add(
        types.InlineKeyboardButton(mode_text, callback_data="toggle_mode"),
        types.InlineKeyboardButton(auto_text, callback_data="toggle_auto")
    )
    markup.add(
        types.InlineKeyboardButton("📊 My Stats", callback_data="my_stats"),
        types.InlineKeyboardButton("🧮 Calculator", callback_data="calc")
    )
    if user_id == ADMIN_ID:
        markup.add(types.InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel"))
    return markup

def get_admin_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
        types.InlineKeyboardButton("👥 Users", callback_data="admin_users")
    )
    markup.add(
        types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🔧 API Status", callback_data="admin_api")
    )
    markup.add(
        types.InlineKeyboardButton("📵 News Block", callback_data="admin_news"),
        types.InlineKeyboardButton("🔴 Kill Switch", callback_data="admin_kill")
    )
    markup.add(types.InlineKeyboardButton("◀️ Back", callback_data="back_main"))
    return markup

def get_pair_menu():
    markup = types.InlineKeyboardMarkup(row_width=3)
    pairs = [
        ("🇪🇺 EURUSD", "EURUSD"), ("🇬🇧 GBPUSD", "GBPUSD"), ("🇯🇵 USDJPY", "USDJPY"),
        ("🇦🇺 AUDUSD", "AUDUSD"), ("🇨🇦 USDCAD", "USDCAD"), ("🟡 GBPJPY", "GBPJPY"),
        ("🟢 EURJPY", "EURJPY"), ("🟠 XAUUSD", "XAUUSD")
    ]
    buttons = [types.InlineKeyboardButton(text, callback_data=f"scan_{code}") for text, code in pairs]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("◀️ Back", callback_data="back_main"))
    return markup

def fetch_candles(symbol, interval='5min', outputsize=50):
    global API_CALL_COUNT
    reset_daily_counters()
    if API_CALL_COUNT >= DAILY_LIMIT:
        return None
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={TWELVE_API_KEY}"
        r = requests.get(url, timeout=10)
        API_CALL_COUNT += 1
        if r.status_code == 200:
            data = r.json()
            if 'values' in data:
                return data['values']
    except Exception as e:
        print(f"API error: {e}")
    return None

def analyze_signal(pair, candles):
    try:
        closes = [float(c['close']) for c in candles[:50]]
        highs = [float(c['high']) for c in candles[:50]]
        lows = [float(c['low']) for c in candles[:50]]
        if len(closes) < 20:
            return None
        sma20 = sum(closes[:20]) / 20
        sma50 = sum(closes[:50]) / 50 if len(closes) >= 50 else sma20
        delta = closes[0] - closes[1]
        gain = delta if delta > 0 else 0
        loss = -delta if delta < 0 else 0
        avg_gain = gain
        avg_loss = loss
        for i in range(1, 14):
            delta = closes[i] - closes[i+1]
            gain = delta if delta > 0 else 0
            loss = -delta if delta < 0 else 0
            avg_gain = (avg_gain * 13 + gain) / 14
            avg_loss = (avg_loss * 13 + loss) / 14
        rs = avg_gain / avg_loss if avg_loss!= 0 else 100
        rsi = 100 - (100 / (1 + rs))
        atr = sum([highs[i] - lows[i] for i in range(14)]) / 14
        price = closes[0]
        signal_type = None
        confidence = 50
        if price > sma20 and sma20 > sma50 and 40 < rsi < 70:
            signal_type = 'CALL'
            confidence = 65 + int((rsi - 40) / 3)
        elif price < sma20 and sma20 < sma50 and 30 < rsi < 60:
            signal_type = 'PUT'
            confidence = 65 + int((60 - rsi) / 3)
        if not signal_type or confidence < MIN_CONFIDENCE:
            return None
        pip_value = 0.01 if 'JPY' in pair else 0.0001
        sl_distance = atr * 1.5
        tp_distance = atr * 2.5
        if signal_type == 'CALL':
            entry = price
            sl = price - sl_distance
            tp = price + tp_distance
        else:
            entry = price
            sl = price + sl_distance
            tp = price - tp_distance
        return {
            'pair': pair,
            'type': signal_type,
            'entry': entry,
            'sl': sl,
            'tp': tp,
            'confidence': min(confidence, 95),
            'rsi': rsi,
            'reason': f"RSI {rsi:.1f} + SMA trend + ATR"
        }
    except Exception as e:
        print(f"Analysis error: {e}")
        return None

def send_signal_to_user(user_id, signal):
    global DAILY_SIGNALS_SENT, USER_TRADE_COUNT
    mode = user_mode.get(user_id, 'po')
    expiry_text = "5min expiry" if mode == 'po' else "No expiry (FOREX)"
    msg = f"""
🎯 **{signal['pair']} - {signal['type']}**

📊 **Entry:** `{signal['entry']:.5f}`
🛑 **SL:** `{signal['sl']:.5f}`
🎯 **TP:** `{signal['tp']:.5f}`
⏱️ **{expiry_text}**
💪 **Confidence:** {signal['confidence']}%
📈 **Reason:** {signal['reason']}

⚠️ **Max Risk: 0.25%**
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ WIN", callback_data=f"win_{user_id}_{signal['pair']}"),
        types.InlineKeyboardButton("❌ LOSS", callback_data=f"loss_{user_id}_{signal['pair']}")
    )
    bot.send_message(user_id, msg, parse_mode='Markdown', reply_markup=markup)
    DAILY_SIGNALS_SENT += 1
    USER_TRADE_COUNT[user_id] = USER_TRADE_COUNT.get(user_id, 0) + 1
    if str(user_id) not in user_stats:
        user_stats[str(user_id)] = {'wins': 0, 'losses': 0, 'signals': []}
    user_stats[str(user_id)]['signals'].append({
        'pair': signal['pair'],
        'type': signal['type'],
        'entry': signal['entry'],
        'time': datetime.now().isoformat()
    })
    if signal['pair'] not in pair_stats:
        pair_stats[signal['pair']] = {'wins': 0, 'losses': 0}
    save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})

def scan_pair_for_user(user_id, pair):
    if not is_trading_hours():
        return "Market closed (22:00-06:00 EAT)"
    if USER_TRADE_COUNT.get(user_id, 0) >= subscribers.get(user_id, {}).get('daily_limit', DEFAULT_TRADE_LIMIT):
        return "Daily limit reached"
    if DAILY_SIGNALS_SENT >= MAX_DAILY_SIGNALS:
        return "Daily signal limit reached"
    last_scan = LAST_TRADE_TIME.get(f"{user_id}_{pair}", datetime.min)
    if datetime.now() - last_scan < timedelta(seconds=SCAN_INTERVAL):
        return "Cooldown active"
    candles = fetch_candles(pair)
    if not candles:
        return "API error"
    signal = analyze_signal(pair, candles)
    LAST_TRADE_TIME[f"{user_id}_{pair}"] = datetime.now()
    if signal:
        send_signal_to_user(user_id, signal)
        return f"Signal sent: {pair} {signal['type']}"
    else:
        pair_last_result[f"{user_id}_{pair}"] = 'no_setup'
        return "No setup found"

# === COMMAND HANDLERS ===
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    if user_id in banned_users:
        bot.reply_to(message, "❌ Access denied")
        return
    if MAINTENANCE_MODE and user_id!= ADMIN_ID:
        bot.reply_to(message, "🔴 Bot under maintenance")
        return
    if user_id not in subscribers or subscribers[user_id]['expiry'] < datetime.now():
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💰 Activate - 7 Days", callback_data="activate_trial"))
        bot.reply_to(message, f"""
🚀 **Denverlyk Trading Bot V3.4**

⚡ Pick-A-Pair System
🎯 ATR-based SL/TP
📊 65%+ Confidence Filter
🛡️ Max 10 trades/day

💵 **M-Pesa:** `{CASH_IN_ID}`
💰 **7 Days Access**

Contact @admin after payment
""", reply_markup=markup)
    else:
        limit = subscribers[user_id].get('daily_limit', DEFAULT_TRADE_LIMIT)
        used = USER_TRADE_COUNT.get(user_id, 0)
        bot.reply_to(message, f"✅ **Welcome back!**\n\nTrades left today: {limit-used}/{limit}", reply_markup=get_main_menu(user_id))

@bot.message_handler(commands=['scan'])
def scan_cmd(message):
    user_id = message.from_user.id
    if user_id in banned_users or MAINTENANCE_MODE:
        return
    if user_id not in subscribers or subscribers[user_id]['expiry'] < datetime.now():
        bot.reply_to(message, "❌ Subscription expired")
        return
    try:
        pair = message.text.split()[1].upper()
        if pair not in PAIRS:
            bot.reply_to(message, f"❌ Invalid pair. Use: {', '.join(PAIRS)}")
            return
        msg = bot.reply_to(message, f"🔍 Scanning {pair}...")
        result = scan_pair_for_user(user_id, pair)
        if "Signal sent" in result:
            bot.delete_message(message.chat.id, msg.message_id)
        else:
            safe_edit(message.chat.id, msg.message_id, f"❌ {result}\n\nTry another pair or wait 1min", reply_markup=get_pair_menu())
    except:
        bot.reply_to(message, "Usage: /scan EURUSD")

# === CALLBACK HANDLERS ===
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    if user_id in banned_users:
        bot.answer_callback_query(call.id, "Banned")
        return
    if call.data == "get_signal":
        if user_id not in subscribers or subscribers[user_id]['expiry'] < datetime.now():
            bot.answer_callback_query(call.id, "Subscription expired")
            return
        safe_edit(call.message.chat.id, call.message.message_id, "🎯 **Pick a pair to scan:**", reply_markup=get_pair_menu())
    elif call.data.startswith("scan_"):
        pair = call.data.split("_")[1]
        msg = bot.edit_message_text(f"🔍 Scanning {pair}...", call.message.chat.id, call.message.message_id)
        result = scan_pair_for_user(user_id, pair)
        if "Signal sent" not in result:
            safe_edit(call.message.chat.id, msg.message_id, f"❌ No setup for {pair}\n\n{result}", reply_markup=get_pair_menu())
    elif call.data == "toggle_mode":
        current = user_mode.get(user_id, 'po')
        user_mode[user_id] = 'forex' if current == 'po' else 'po'
        save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.answer_callback_query(call.id, f"Mode: {user_mode[user_id].upper()}")
        safe_edit(call.message.chat.id, call.message.message_id, "⚙️ Settings updated", reply_markup=get_main_menu(user_id))
    elif call.data == "toggle_auto":
        if user_id in auto_scan_users:
            auto_scan_users.remove(user_id)
        else:
            auto_scan_users.append(user_id)
        save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.answer_callback_query(call.id, "Auto scan toggled")
        safe_edit(call.message.chat.id, call.message.message_id, "⚙️ Settings updated", reply_markup=get_main_menu(user_id))
    elif call.data == "my_stats":
        stats = user_stats.get(str(user_id), {'wins': 0, 'losses': 0})
        total = stats['wins'] + stats['losses']
        wr = (stats['wins'] / total * 100) if total > 0 else 0
        limit = subscribers.get(user_id, {}).get('daily_limit', DEFAULT_TRADE_LIMIT)
        used = USER_TRADE_COUNT.get(user_id, 0)
        safe_edit(call.message.chat.id, call.message.message_id, f"""
📊 **YOUR STATS**

✅ Wins: {stats['wins']}
❌ Losses: {stats['losses']}
🎯 Win Rate: {wr:.1f}%
📈 Trades Today: {used}/{limit}

Expires: {subscribers[user_id]['expiry'].strftime('%d %b %Y')}
""", reply_markup=get_main_menu(user_id))
    elif call.data == "calc":
        safe_edit(call.message.chat.id, call.message.message_id, "🧮 **Position Size Calculator**\n\nSend: `/calc balance risk% sl_pips`\nExample: `/calc 1000 0.25 20`")
    elif call.data == "admin_panel":
        if user_id!= ADMIN_ID: return
        safe_edit(call.message.chat.id, call.message.message_id, "👑 **ADMIN PANEL**", reply_markup=get_admin_menu())
    elif call.data == "back_main":
        safe_edit(call.message.chat.id, call.message.message_id, "🏠 Main Menu", reply_markup=get_main_menu(user_id))
    elif call.data.startswith("win_") or call.data.startswith("loss_"):
        parts = call.data.split("_")
        result = parts[0]
        target_user = int(parts[1])
        pair = parts[2]
        if str(target_user) not in user_stats:
            user_stats[str(target_user)] = {'wins': 0, 'losses': 0, 'signals': []}
        if result == "win":
            user_stats[str(target_user)]['wins'] += 1
            pair_stats[pair]['wins'] = pair_stats.get(pair, {}).get('wins', 0) + 1
            pair_last_result[f"{target_user}_{pair}"] = 'win'
        else:
            user_stats[str(target_user)]['losses'] += 1
            pair_stats[pair]['losses'] = pair_stats.get(pair, {}).get('losses', 0) + 1
            pair_last_result[f"{target_user}_{pair}"] = 'loss'
        save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.answer_callback_query(call.id, f"Logged: {result.upper()}")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    elif call.data == "activate_trial":
        if user_id in subscribers:
            bot.answer_callback_query(call.id, "Already subscribed")
            return
        expiry = datetime.now() + timedelta(days=7)
        subscribers[user_id] = {'expiry': expiry, 'daily_limit': DEFAULT_TRADE_LIMIT}
        user_mode[user_id] = 'po'
        save_data({'subscribers': {str(k): {'expiry': v['expiry'].isoformat(), 'daily_limit': v.get('daily_limit', DEFAULT_TRADE_LIMIT)} for k, v in subscribers.items()}, 'user_mode': user_mode, 'user_stats': user_stats, 'pair_stats': pair_stats, 'banned': banned_users, 'auto_scan': auto_scan_users, 'pair_last_result': pair_last_result})
        bot.answer_callback_query(call.id, "Activated!")
        bot.send_message(ADMIN_ID, f"🆕 New user: {user_id}\n@{call.from_user.username}")
        safe_edit(call.message.chat.id, call.message.message_id, f"✅ **Activated for 7 days!**\n\nExpires: {expiry.strftime('%d %b %Y')}\n\nTap /start", reply_markup=get_main_menu(user_id))

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_panel_callback(call):
    global MANUAL_NEWS_BLOCK, MAINTENANCE_MODE
    if call.from_user.id!= ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin only")
        return
    try:
        action = call.data.split('_')[1]
        if action == 'stats':
            total_users = len(subscribers)
            active_subs = sum(1 for uid, sub in subscribers.items() if sub['expiry'] > datetime.now())
            total_signals = sum(len(user_stats.get(str(uid), {}).get('signals', [])) for uid in subscribers.keys())
            total_wins = sum(user_stats.get(str(uid), {}).get('wins', 0) for uid in subscribers.keys())
            total_losses = sum(user_stats.get(str(uid), {}).get('losses', 0) for uid in subscribers.keys())
            tracked = total_wins + total_losses
            global_wr = (total_wins / tracked * 100) if tracked > 0 else 0
            safe_edit(call.message.chat.id, call.message.message_id, f"""
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
""", reply_markup=get_admin_menu())
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
            safe_edit(call.message.chat.id, call.message.message_id, msg, reply_markup=get_admin_menu())
        elif action == 'broadcast':
            safe_edit(call.message.chat.id, call.message.message_id, "📢 Send: `/broadcast your message here`")
        elif action == 'api':
            reset_time = (API_CALL_RESET + timedelta(days=1)).strftime('%H:%M EAT')
            safe_edit(call.message.chat.id, call.message.message_id, f"""
📊 **API STATUS V3.4**

Used: {API_CALL_COUNT}/{DAILY_LIMIT}
Left: {DAILY_LIMIT - API_CALL_COUNT}
Reset: {reset_time}

Status: {'✅ SAFE' if API_CALL_COUNT < DAILY_LIMIT-100 else '⚠️ LIMIT'}
Cache: {len(CANDLE_DB)} pairs
Interval: {SCAN_INTERVAL}s
Signals Today: {DAILY_SIGNALS_SENT}/{MAX_DAILY_SIGNALS}
Maintenance: {'🔴 ON' if MAINTENANCE_MODE else '🟢 OFF'}
News Block: {'🔴 ON' if MANUAL_NEWS_BLOCK else '🟢 OFF'}
""", reply_markup=get_admin_menu())
        elif action == 'news':
            MANUAL_NEWS_BLOCK = not MANUAL_NEWS_BLOCK
            status = "🔴 ON" if MANUAL_NEWS_BLOCK else "🟢 OFF"
            bot.answer_callback_query(call.id, f"News Block: {status}")
            safe_edit(call.message.chat.id, call.message.message_id, f"📵 News Block: {status}", reply_markup=get_admin_menu())
        elif action == 'kill':
            MAINTENANCE_MODE = not MAINTENANCE_MODE
            status = "🔴 ON" if MAINTENANCE_MODE else "🟢 OFF"
            bot.answer_callback_query(call.id, f"Maintenance: {status}")
            safe_edit(call.message.chat.id, call.message.message_id, f"🔴 Maintenance: {status}", reply_markup=get_admin_menu())
    except Exception as e:
        bot.answer_callback_query(call.id, "Error occurred")
        bot.send_message(ADMIN_ID, f"❌ Admin panel error:\n{str(e)}\n\n{traceback.format_exc()}")

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

@bot.message_handler(commands=['api'])
def api_cmd(message):
    if message.from_user.id!= ADMIN_ID: return
    reset_time = (API_CALL_RESET + timedelta(days=1)).strftime('%H:%M EAT')
    bot.reply_to(message, f"""
📊 **API STATUS V3.4**

Used: {API_CALL_COUNT}/{DAILY_LIMIT}
Left: {DAILY_LIMIT - API_CALL_COUNT}
Reset: {reset_time}

Status: {'✅ SAFE' if API_CALL_COUNT < DAILY_LIMIT-100 else '⚠️ LIMIT'}
Cache: {len(CANDLE_DB)} pairs
Signals Today: {DAILY_SIGNALS_SENT}/{MAX_DAILY_SIGNALS}
""")

def run_bot():
    try:
        bot.remove_webhook()
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(2)
        print(f"Bot online: @{bot.get_me().username}")
        print(f"Admin: {ADMIN_ID}")
        print("Safety: Max 10 trades/user/day | ATR SL/TP")
        print("Denverlyk V3.4 PICK-A-PAIR Starting...")
        print("Scan: User-triggered | 60s cooldown")
        print(f"TwelveData: {'SET' if TWELVE_API_KEY else 'NOT SET'}...")
        bot.infinity_polling(none_stop=True, skip_pending=True, timeout=60)
    except Exception as e:
        print(f"Fatal error: {e}")
        time.sleep(15)

if __name__ == "__main__":
    reset_daily_counters()
    run_bot()
