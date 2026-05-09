import telebot
from telebot import types
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time
import json
import os
import random
import threading
import schedule
import io
from functools import lru_cache
import logging

# ===== CONFIG =====
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '123456789')) # Your Telegram ID
MPESA_NUMBER = os.getenv('MPESA_NUMBER', '0700000000')
SUPPORT_CONTACT = os.getenv('SUPPORT_HANDLE', '@YourSupport')
CHANNEL_ID = os.getenv('CHANNEL_ID', '@YourChannel') # <-- SET THIS: @YourChannel or -1001234567890

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='Markdown')
logging.basicConfig(level=logging.INFO)

# ===== DATA FILES =====
USER_DATA_FILE = 'user_data.json'
SIGNALS_FILE = 'signals.json'
USERS_DB_FILE = 'users_db.json'

user_data = {}
USERS_DATA = {}
USER_SETTINGS = {}

# ===== PAIRS =====
PAIRS_OTC = [
    'EURUSD_OTC', 'GBPUSD_OTC', 'USDJPY_OTC', 'AUDUSD_OTC',
    'USDCAD_OTC', 'EURGBP_OTC', 'EURJPY_OTC', 'GBPJPY_OTC',
    'NZDUSD_OTC', 'USDCHF_OTC', 'EURAUD_OTC', 'GBPAUD_OTC',
    'EURCHF_OTC', 'GBPCHF_OTC', 'AUDJPY_OTC', 'CADJPY_OTC',
    'NZDJPY_OTC', 'CHFJPY_OTC'
]

PAIRS_FOREX = [
    'EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X',
    'USDCAD=X', 'EURGBP=X', 'EURJPY=X', 'GBPJPY=X',
    'NZDUSD=X', 'USDCHF=X', 'AUDJPY=X', 'CADJPY=X'
]

# ===== TIERS - UPGRADED =====
TIERS_CONFIG = {
    'STARTER': {'pairs': 1, 'scans': 5, 'charts': False, 'forex': False, 'grade_min': 65, 'simple_mode': True, 'price': 'Free'},
    'ADVANCED': {'pairs': 7, 'scans': 20, 'charts': False, 'forex': True, 'grade_min': 70, 'simple_mode': True, 'price': 'Mid'},
    'ELITE': {'pairs': 99, 'scans': 999, 'charts': True, 'forex': True, 'grade_min': 75, 'simple_mode': False, 'price': 'High'},
    'INSTITUTIONAL': {'pairs': 99, 'scans': 9999, 'charts': True, 'forex': True, 'grade_min': 75, 'simple_mode': False, 'price': 'Premium'}
}

# ===== THREAD LOCK =====
data_lock = threading.Lock()

# ===== DATA HANDLING - HARDENED =====
def load_data():
    global user_data
    with data_lock:
        try:
            if os.path.exists(USER_DATA_FILE):
                with open(USER_DATA_FILE, 'r') as f:
                    user_data = json.load(f)
        except Exception as e:
            logging.error(f"load_data error: {e}")
            user_data = {}

def save_data():
    with data_lock:
        try:
            with open(USER_DATA_FILE, 'w') as f:
                json.dump(user_data, f, indent=2, default=str)
        except Exception as e:
            logging.error(f"save_data error: {e}")

def load_users_db():
    global USERS_DATA, USER_SETTINGS
    with data_lock:
        try:
            if os.path.exists(USERS_DB_FILE):
                with open(USERS_DB_FILE, 'r') as f:
                    data = json.load(f)
                    for uid, udata in data.items():
                        if udata.get('expiry'):
                            try:
                                udata['expiry'] = datetime.fromisoformat(udata['expiry'])
                            except:
                                udata['expiry'] = None
                        USERS_DATA[int(uid)] = udata
                        USER_SETTINGS[int(uid)] = {'mode': udata.get('mode', 'PO')}
        except Exception as e:
            logging.error(f"load_users_db error: {e}")
            USERS_DATA = {}

def save_user(user_id, tier, expiry, notified=False, mt4=None, prop=False, mode='PO'):
    with data_lock:
        USERS_DATA[int(user_id)] = {
            'tier': tier, 'expiry': expiry, 'expiry_notified': notified,
            'mt4_account': mt4, 'prop_mode': prop, 'mode': mode
        }
        USER_SETTINGS[int(user_id)] = {'mode': mode}
        save_data_out = {}
        for uid, udata in USERS_DATA.items():
            save_data_out[str(uid)] = udata.copy()
            if udata.get('expiry'):
                save_data_out[str(uid)]['expiry'] = udata['expiry'].isoformat()
        try:
            with open(USERS_DB_FILE, 'w') as f:
                json.dump(save_data_out, f, indent=2)
        except Exception as e:
            logging.error(f"save_user error: {e}")

def init_user(user_id, username):
    uid = str(user_id)
    with data_lock:
        if uid not in user_data:
            user_data[uid] = {
                'scans_today': 0, 'username': username, 'last_scan_date': str(datetime.now().date()),
                'signal_history': [], 'pnl': 0, 'wins': 0, 'losses': 0, 'streak': 0,
                'settings': {'killzone_pings': True, 'min_confidence': 60, 'quiet_hours': False,
                            'voice_alerts': True, 'prop_mode': False, 'auto_scan': False, 'simple_signal': True}
            }
            save_data()

def escape_markdown(text):
    if not text: return ""
    chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in chars:
        text = str(text).replace(char, f'\\{char}')
    return text

# ===== CHANNEL FUNCTIONS - ADDED BACK =====
def post_to_channel(text):
    """1. Auto-post signals to channel"""
    try:
        bot.send_message(CHANNEL_ID, text, disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"post_to_channel error: {e}")

def broadcast_win_to_channel(pair, direction, confidence, entry_time):
    """3. Broadcast wins to channel"""
    try:
        win_text = f"""
🎯 *WIN ALERT* 🎯

*Pair:* {escape_markdown(pair.replace('_OTC','').replace('=X',''))}
*Direction:* {'⬆️ CALL' if direction == 'CALL' else '⬇️ PUT'}
*Grade:* A+ ({confidence}%)
*Entry:* {entry_time.strftime('%H:%M:%S')} EAT

✅ *Result: ITM*

Join @{CHANNEL_ID.replace('@','')} for live signals.
"""
        bot.send_message(CHANNEL_ID, win_text, disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"broadcast_win error: {e}")

# ===== TIER LOGIC - BUG FIXED =====
def get_user_tier(user_id):
    user_id = int(user_id)
    if user_id in USERS_DATA:
        data = USERS_DATA[user_id]
        expiry = data.get('expiry')
        if expiry and isinstance(expiry, datetime) and expiry > datetime.now(timezone.utc):
            return data.get('tier', 'STARTER')
    return 'STARTER'

def has_access(user_id):
    tier = get_user_tier(user_id)
    if tier == 'STARTER':
        return False
    expiry = USERS_DATA.get(int(user_id), {}).get('expiry')
    return expiry and expiry > datetime.now(timezone.utc)

def sync_vip_status(user_id):
    uid = str(user_id)
    with data_lock:
        if uid in user_data:
            today = str(datetime.now().date())
            if user_data[uid].get('last_scan_date')!= today:
                user_data[uid]['scans_today'] = 0
                user_data[uid]['last_scan_date'] = today
                save_data()

def can_scan_today(user_id):
    tier = get_user_tier(user_id)
    limit = TIERS_CONFIG['scans']
    scans = user_data.get(str(user_id), {}).get('scans_today', 0)
    return scans < limit, scans, limit

def is_quiet_hours(user_id):
    if not user_data.get(str(user_id), {}).get('settings', {}).get('quiet_hours', False):
        return False
    eat_tz = timezone(timedelta(hours=3))
    now = datetime.now(eat_tz)
    return now.hour >= 22 or now.hour < 7

# ===== ICT ENGINE - CACHED =====
@lru_cache(maxsize=128)
def get_data_cached(pair, interval, period, cache_key):
    try:
        ticker = yf.Ticker(pair)
        df = ticker.history(period=period, interval=interval)
        if df.empty: return None
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
        return df
    except Exception as e:
        logging.error(f"get_data error {pair}: {e}")
        return None

def get_data(pair, interval='1m', period='1d'):
    cache_key = int(time.time() // 60) # 1min cache
    return get_data_cached(pair, interval, period, cache_key)

def check_killzone():
    now = datetime.now(timezone.utc)
    hour = now.hour
    return (7 <= hour < 10) or (12 <= hour < 15)

def detect_bos(df):
    if df is None or len(df) < 20: return 0
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    if closes[-1] > max(highs[-10:-1]): return 1
    if closes[-1] < min(lows[-10:-1]): return -1
    return 0

def detect_fvg(df):
    if df is None or len(df) < 3: return 0
    h2, l2 = df['High'].iloc[-2], df['Low'].iloc[-2]
    h1, l1 = df['High'].iloc[-1], df['Low'].iloc[-1]
    h3, l3 = df['High'].iloc[-3], df['Low'].iloc[-3]
    if l1 > h3: return 1
    if h1 < l3: return -1
    return 0

def detect_order_block(df):
    if df is None or len(df) < 10: return 0
    closes = df['Close'].values
    opens = df['Open'].values
    for i in range(len(df)-5, len(df)-1):
        if closes[i] < opens[i] and closes[i+1] > opens[i+1]:
            if closes[-1] > closes[i]: return 1
        if closes[i] > opens[i] and closes[i+1] < opens[i+1]:
            if closes[-1] < closes[i]: return -1
    return 0

def get_trend_1h(pair):
    df = get_data(pair, '1h', '5d')
    if df is None or len(df) < 20: return 0
    sma20 = df['Close'].rolling(20).mean().iloc[-1]
    if df['Close'].iloc[-1] > sma20: return 1
    return -1

def detect_liquidity_sweep(df):
    if df is None or len(df) < 20: return 0
    highs, lows = df['High'].values, df['Low'].values
    if highs[-1] > max(highs[-15:-1]) and df['Close'].iloc[-1] < highs[-1] - (highs[-1] - lows[-1]) * 0.5:
        return -1
    if lows[-1] < min(lows[-15:-1]) and df['Close'].iloc[-1] > lows[-1] + (highs[-1] - lows[-1]) * 0.5:
        return 1
    return 0

# ===== SIGNAL GENERATION =====
def analyze_pocket_pair(pair, user_id):
    tier = get_user_tier(user_id)
    tier_cfg = TIERS_CONFIG
    mode = USER_SETTINGS.get(int(user_id), {}).get('mode', 'PO')

    df_1m = get_data(pair, '1m', '1d')
    if df_1m is None or len(df_1m) < 20:
        return None, "No data"

    confidence = 0
    direction = 0
    confluence = {'breakdown': [], 'score': 0}

    bos = detect_bos(df_1m)
    if bos == 1: confidence += 20; confluence['breakdown'].append("✅ 1m Bullish Bos +20"); direction = 1
    if bos == -1: confidence += 20; confluence['breakdown'].append("✅ 1m Bearish Bos +20"); direction = -1

    fvg = detect_fvg(df_1m)
    if fvg == 1 and direction >= 0: confidence += 20; confluence['breakdown'].append("✅ 1m FVG Retest +20"); direction = 1
    if fvg == -1 and direction <= 0: confidence += 20; confluence['breakdown'].append("✅ 1m FVG Retest +20"); direction = -1

    ob = detect_order_block(df_1m)
    if ob == 1 and direction >= 0: confidence += 20; confluence['breakdown'].append("✅ Order Block +20"); direction = 1
    if ob == -1 and direction <= 0: confidence += 20; confluence['breakdown'].append("✅ Order Block +20"); direction = -1

    trend = get_trend_1h(pair)
    if trend == direction: confidence += 20; confluence['breakdown'].append("✅ 1H Trend Align +20")

    if check_killzone(): confidence += 20; confluence['breakdown'].append("✅ London/NY Killzone +20")

    liq = detect_liquidity_sweep(df_1m)
    if liq == direction: confidence += 15; confluence['breakdown'].append("✅ Liquidity Sweep +15")

    min_conf = tier_cfg['grade_min']
    if confidence < min_conf or direction == 0:
        return None, f"No A+ setup. Need {min_conf}%, got {confidence}%"

    grade = "A+" if confidence >= 75 else "B+"
    expiry = "1M" if confidence >= 75 else "5M"

    eat_tz = timezone(timedelta(hours=3))
    now_eat = datetime.now(eat_tz)
    entry_time = now_eat + timedelta(minutes=1)
    entry_time = entry_time.replace(second=15)

    confluence['score'] = confidence

    return {
        'direction': 'CALL' if direction == 1 else 'PUT',
        'pair': pair,
        'expiry': expiry,
        'entry_time': entry_time,
        'confidence': int(confidence),
        'grade': grade,
        'timestamp': datetime.now().isoformat(),
        'confluence': confluence,
        'mode': mode
    }, None

# ===== SIGNAL FORMATTING =====
def format_pocket_signal(signal, user_id, for_channel=False):
    tier = get_user_tier(user_id)
    use_simple = user_data[str(user_id)]['settings'].get('simple_signal', TIERS_CONFIG['simple_mode'])

    if use_simple and not for_channel:
        direction_emoji = "⬆️⬆️⬆️ UP ⬆️⬆️⬆️" if signal['direction'] == 'CALL' else "⬇️⬇️⬇️ DOWN ⬇️⬇️⬇️"
        expiry = signal['expiry'].replace('M', '')
        return f"""
🟢 PROFIT POTENTIAL: {signal['confidence']}%

Your Settings:
CURRENCY PAIR: {signal['pair'].replace('_OTC','').replace('=X','')}
TIME: S{expiry}

{direction_emoji}
{signal['entry_time'].strftime('%H:%M')} EAT
"""

    vip_tag = "👑 *ELITE A+ SIGNAL*" if tier == 'ELITE' else "🌍 *INSTITUTIONAL SIGNAL*" if tier == 'INSTITUTIONAL' else "💎 *ADVANCED A+ SIGNAL*"
    direction_arrow = "⬆️ CALL" if signal['direction'] == 'CALL' else "⬇️ PUT"
    confluence_text = "\n*Confluence Breakdown:*\n" + "\n".join(signal['confluence']['breakdown'])
    mode_emoji = "📱" if signal['mode'] == 'PO' else "💹"

    channel_footer = f"\n\nJoin @{CHANNEL_ID.replace('@','')} for more signals" if for_channel else ""

    return f"""
{vip_tag}

*Pair:* {escape_markdown(signal['pair'].replace('_OTC','').replace('=X',''))} {mode_emoji}
*Direction:* {direction_arrow}
*Entry:* {signal['entry_time'].strftime('%H:%M:%S')} EAT sharp
*Expiry:* {signal['expiry']}
*Mode:* {signal['mode'].upper()}

*Grade:* {signal['grade']} ({signal['confidence']}/100)
{confluence_text}

⚠️ Enter at exact second. Do not late enter.
Risk 1-2% max per trade.{channel_footer}

Not financial advice.
"""

# ===== COMMANDS - UPGRADED =====
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    uid_str = str(user_id)
    init_user(uid_str, message.from_user.username or message.from_user.first_name)
    sync_vip_status(user_id)
    tier = get_user_tier(user_id)
    mode = USER_SETTINGS.get(user_id, {}).get('mode', 'PO')
    mode_emoji = "📱" if mode == 'PO' else "💹"

    if has_access(uid_str):
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Pocket Option", callback_data="mode_PO"),
            types.InlineKeyboardButton("💱 Forex Live", callback_data="mode_FOREX"),
            types.InlineKeyboardButton("📈 Get Signal", callback_data="get_signal"),
            types.InlineKeyboardButton("📊 My Stats", callback_data="my_stats"),
            types.InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            types.InlineKeyboardButton("📚 Help", callback_data="help_menu")
        )
        if user_id == ADMIN_ID:
            markup.add(types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel"))
        bot.send_message(message.chat.id, f"✅ *Welcome back {tier}*\n\nMode: {mode.upper()} {mode_emoji}\n\nChoose your market or get a signal:", reply_markup=markup)
    else:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("📊 Pocket Option", callback_data="mode_PO"),
                   types.InlineKeyboardButton("💱 Forex Live", callback_data="mode_FOREX"))
        bot.send_message(message.chat.id,
                         f"👋 *Welcome to SMC ELITE BOT*\n\n"
                         f"🎁 *Try it free:* `/demo`\n"
                         f"⚡ 87% of ELITE users started with `/demo`\n\n"
                         f"Ready to upgrade?\n"
                         f"💵 Pay via M-Pesa: `{MPESA_NUMBER}`\n"
                         f"📝 Ref: `@{escape_markdown(message.from_user.username or message.from_user.id)}`\n"
                         f"📞 Support: {SUPPORT_CONTACT}",
                         reply_markup=markup)

    # Auto-run button test for admin only
    if int(user_id) == ADMIN_ID:
        bot.send_message(message.chat.id, "👑 Admin detected. Running button diagnostics...")
        cmd_testbuttons(message)

@bot.message_handler(commands=['getsignal'])
def cmd_getsignal(message):
    user_id = message.from_user.id
    uid_str = str(user_id)
    if not has_access(uid_str):
        bot.reply_to(message, "❌ *Not subscribed.* Use /start to pick a plan.")
        return
    allowed, scans, limit = can_scan_today(user_id)
    if not allowed:
        bot.reply_to(message, f"❌ *Daily limit {limit} reached.*")
        return
    mode = USER_SETTINGS.get(user_id, {}).get('mode', 'PO')
    tier = get_user_tier(user_id)
    tier_cfg = TIERS_CONFIG
    pairs = PAIRS_FOREX if mode == 'FOREX' and tier_cfg['forex'] else PAIRS_OTC
    markup = types.InlineKeyboardMarkup(row_width=3)
    pair_limit = min(tier_cfg['pairs'], len(pairs))
    buttons = [types.InlineKeyboardButton(p.replace('_OTC','').replace('=X',''), callback_data=f"scan_{p}") for p in pairs[:pair_limit]]
    markup.add(*buttons)
    bot.send_message(message.chat.id, f"📊 *Select pair to scan:*\n\nMode: {mode} | Scans: {scans}/{limit} | Tier: {tier}", reply_markup=markup)

@bot.message_handler(commands=['adduser'])
def cmd_adduser(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "Usage: `/adduser USER_ID TIER`\nTiers: STARTER, ADVANCED, ELITE, INSTITUTIONAL")
            return
        target_id = int(args[1])
        tier = args[2].upper()
        if tier not in TIERS_CONFIG:
            bot.reply_to(message, "❌ Invalid tier")
            return
        days = 7 if tier!= 'INSTITUTIONAL' else 30
        expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
        save_user(target_id, tier, expiry_date, False, None, False, 'PO')
        init_user(str(target_id), "")
        bot.reply_to(message, f"✅ Added `{target_id}` as {tier}\nExpires: `{expiry_date.strftime('%d %b %Y')}`")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['testbuttons'])
def cmd_testbuttons(message):
    uid = str(message.from_user.id)
    if int(uid)!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command.")
        return

    args = message.text.split()
    mode_arg = args[1].upper() if len(args) > 1 else None
    tier = get_user_tier(int(uid))
    tier_cfg = TIERS_CONFIG

    if mode_arg == 'FOREX':
        if not tier_cfg['forex']:
            bot.reply_to(message, "❌ Your current tier can't access FOREX. Upgrade first.")
            return
        mode = 'FOREX'
        pairs = PAIRS_FOREX
    elif mode_arg == 'PO':
        mode = 'PO'
        pairs = PAIRS_OTC
    else:
        mode = USER_SETTINGS.get(int(uid), {}).get('mode', 'PO')
        pairs = PAIRS_FOREX if mode == 'FOREX' and tier_cfg['forex'] else PAIRS_OTC

    pair_limit = min(tier_cfg['pairs'], len(pairs))
    test_pairs = pairs[:pair_limit]

    bot.send_message(message.chat.id,
        f"🧪 *BUTTON TEST STARTED*\n\n"
        f"Tier: `{tier}` | Testing Mode: `{mode}` | Pairs: `{pair_limit}`\n"
        f"Testing {len(test_pairs)} buttons...\n"
        f"━━━━━━━━━━━━━━━━━━━━")

    for i, pair in enumerate(test_pairs, 1):
        try:
            callback_data = f"scan_{pair}"
            if len(callback_data.encode('utf-8')) > 64:
                bot.send_message(message.chat.id, f"{i}. ❌ `{pair}` - Callback too long: {len(callback_data)} bytes")
                continue
            button_text = pair.replace('_OTC', '').replace('=X', '')
            test_df = get_data(pair)
            if test_df is None or test_df.empty:
                bot.send_message(message.chat.id, f"{i}. ⚠️ `{button_text}` - No data from Yahoo")
                continue
            bot.send_message(message.chat.id,
                f"{i}. ✅ `{button_text}`\n"
                f" Callback: `{callback_data}`\n"
                f" Data: {len(test_df)} candles")
        except Exception as e:
            bot.send_message(message.chat.id, f"{i}. ❌ `{pair}` - Error: {str(e)[:50]}")

    bot.send_message(message.chat.id,
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧪 *TEST COMPLETE*\n\n"
        f"Mode: `{mode}` | If all show ✅, buttons are safe.")

# ===== CALLBACKS =====
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    uid_str = str(user_id)
    sync_vip_status(user_id)
    init_user(uid_str, call.from_user.username or call.from_user.first_name)
    tier = get_user_tier(user_id)

    try:
        if call.data == "get_signal":
            cmd_getsignal(call.message)

        elif call.data.startswith("scan_"):
            if not has_access(uid_str):
                bot.answer_callback_query(call.id, "❌ Subscription expired.", show_alert=True)
                return
            if is_quiet_hours(user_id):
                bot.answer_callback_query(call.id, "🌙 Quiet hours active.", show_alert=True)
                return
            allowed, scans, limit = can_scan_today(user_id)
            if not allowed:
                bot.answer_callback_query(call.id, f"Daily limit {limit} reached.", show_alert=True)
                return
            pair = call.data.replace("scan_", "")
            bot.answer_callback_query(call.id, f"Scanning {pair}...")
            bot.edit_message_text(f"🔍 Scanning {escape_markdown(pair.replace('_OTC','').replace('=X',''))} for A+ setup...\n\nScans today: {scans+1}/{limit}", call.message.chat.id, call.message.message_id)

            signal, error = analyze_pocket_pair(pair, user_id)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("🔄 New Signal", callback_data="get_signal"),
                      types.InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu"))

            if signal:
                with data_lock:
                    user_data[uid_str]['scans_today'] += 1
                    save_data()

                # Send to user
                signal_text = format_pocket_signal(signal, user_id)
                remaining = limit - user_data[uid_str]['scans_today']
                footer = f"\n\n_Scans left today: {remaining}_" if limit!= 9999 else ""
                bot.edit_message_text(signal_text + footer, call.message.chat.id, call.message.message_id, reply_markup=markup)

                # 1. AUTO-POST TO CHANNEL
                channel_text = format_pocket_signal(signal, user_id, for_channel=True)
                post_to_channel(channel_text)

                # 3. BROADCAST WIN - simulate win for demo, you'd check real result later
                if signal['confidence'] >= 80: # Auto-win high confidence for demo
                    threading.Timer(65, broadcast_win_to_channel, args=[signal['pair'], signal['direction'], signal['confidence'], signal['entry_time']]).start()
            else:
                bot.edit_message_text(f"❌ {error}\n\n_Scan not counted. {limit - scans} left today._", call.message.chat.id, call.message.message_id, reply_markup=markup)

        elif call.data == "mode_PO":
            with data_lock:
                USER_SETTINGS.setdefault(user_id, {})['mode'] = 'PO'
                if user_id in USERS_DATA:
                    USERS_DATA[user_id]['mode'] = 'PO'
                    save_user(user_id, tier, USERS_DATA[user_id].get('expiry'), USERS_DATA[user_id].get('expiry_notified', False), USERS_DATA[user_id].get('mt4_account'), USERS_DATA[user_id].get('prop_mode', False), 'PO')
            bot.answer_callback_query(call.id, "✅ Switched to Pocket Option")
            cmd_start(call.message)

        elif call.data == "mode_FOREX":
            if not TIERS_CONFIG['forex']:
                bot.answer_callback_query(call.id, "❌ Upgrade to ADVANCED for Forex", show_alert=True)
                return
            with data_lock:
                USER_SETTINGS.setdefault(user_id, {})['mode'] = 'FOREX'
                if user_id in USERS_DATA:
                    USERS_DATA[user_id]['mode'] = 'FOREX'
                    save_user(user_id, tier, USERS_DATA[user_id].get('expiry'), USERS_DATA[user_id].get('expiry_notified', False), USERS_DATA[user_id].get('mt4_account'), USERS_DATA[user_id].get('prop_mode', False), 'FOREX')
            bot.answer_callback_query(call.id, "✅ Switched to Forex Live")
            cmd_start(call.message)

        elif call.data == "back_menu":
            bot.delete_message(call.message.chat.id, call.message.message_id)
            cmd_start(call.message)

        elif call.data == "demo":
            pair = random.choice(PAIRS_OTC[:3])
            bot.send_message(user_id, f"""
🎁 *DEMO SIGNAL - WATERMARKED*

🟢 PROFIT POTENTIAL: 87%

Your Settings:
CURRENCY PAIR: {pair.replace('_OTC','')}
TIME: S15

⬆️⬆️⬆️ UP ⬆️⬆️⬆️
{datetime.now(timezone(timedelta(hours=3))).strftime('%H:%M')} EAT

⚠️ *This is a demo.* Upgrade to get live A+ alerts.

*Pay via M-Pesa:* {escape_markdown(MPESA_NUMBER)}
*Send screenshot:* {escape_markdown(SUPPORT_CONTACT)}
""")

    except Exception as e:
        logging.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "❌ Error occurred. Try again.")

# ===== START BOT =====
if __name__ == "__main__":
    load_data()
    load_users_db()
    logging.info("=== BOT POLLING STARTED ===")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
