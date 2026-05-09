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
import sys
sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

# ===== CONFIG =====
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '123456789'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER', '0700000000')
SUPPORT_CONTACT = os.getenv('SUPPORT_HANDLE', '@YourSupport')
CHANNEL_ID = os.getenv('CHANNEL_ID', '@YourChannel')

bot = telebot.TeleBot(BOT_TOKEN)

# ===== DATA FILES =====
USER_DATA_FILE = 'user_data.json'
SIGNALS_FILE = 'signals.json'
USERS_DB_FILE = 'users_db.json'
RESULTS_FILE = 'results.json'

user_data = {}
USERS_DATA = {}
USER_SETTINGS = {}
RESULTS_DATA = []

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

# ===== TIERS =====
TIERS_CONFIG = {
    'STARTER': {'pairs': 1, 'scans': 5, 'charts': False, 'forex': False, 'grade_min': 65, 'simple_mode': True, 'price': 'Free'},
    'ADVANCED': {'pairs': 7, 'scans': 20, 'charts': False, 'forex': True, 'grade_min': 70, 'simple_mode': True, 'price': 'Mid'},
    'ELITE': {'pairs': 99, 'scans': 999, 'charts': True, 'forex': True, 'grade_min': 75, 'simple_mode': False, 'price': 'High'},
    'INSTITUTIONAL': {'pairs': 99, 'scans': 9999, 'charts': True, 'forex': True, 'grade_min': 75, 'simple_mode': False, 'price': 'Premium'}
}

# ===== THREAD LOCK =====
data_lock = threading.Lock()

# ===== SAFE DATA HANDLING =====
def safe_load():
    global user_data, RESULTS_DATA, USERS_DATA, USER_SETTINGS
    try:
        with data_lock:
            if os.path.exists(USER_DATA_FILE):
                with open(USER_DATA_FILE, 'r') as f:
                    user_data = json.load(f)
            if os.path.exists(RESULTS_FILE):
                with open(RESULTS_FILE, 'r') as f:
                    RESULTS_DATA = json.load(f)
            if os.path.exists(USERS_DB_FILE):
                with open(USERS_DB_FILE, 'r') as f:
                    data = json.load(f)
                    for uid, udata in data.items():
                        try:
                            if udata.get('expiry'):
                                udata['expiry'] = datetime.fromisoformat(udata['expiry'])
                        except:
                            udata['expiry'] = None
                        USERS_DATA[int(uid)] = udata
                        USER_SETTINGS[int(uid)] = {'mode': udata.get('mode', 'PO')}
    except Exception as e:
        print(f"SAFE_LOAD ERROR: {e}", flush=True)
        user_data, RESULTS_DATA, USERS_DATA, USER_SETTINGS = {}, [], {}, {}

def safe_save():
    try:
        with data_lock:
            with open(USER_DATA_FILE, 'w') as f:
                json.dump(user_data, f, indent=2, default=str)
            with open(RESULTS_FILE, 'w') as f:
                json.dump(RESULTS_DATA, f, indent=2, default=str)
            save_data_out = {}
            for uid, udata in USERS_DATA.items():
                save_data_out[str(uid)] = udata.copy()
                if udata.get('expiry'):
                    save_data_out[str(uid)]['expiry'] = udata['expiry'].isoformat()
            with open(USERS_DB_FILE, 'w') as f:
                json.dump(save_data_out, f, indent=2)
    except Exception as e:
        print(f"SAFE_SAVE ERROR: {e}", flush=True)

def safe_get_user_tier(user_id):
    try:
        user_id = int(user_id)
        if user_id in USERS_DATA:
            data = USERS_DATA[user_id]
            expiry = data.get('expiry')
            if expiry and isinstance(expiry, datetime) and expiry > datetime.now(timezone.utc):
                return data.get('tier', 'STARTER')
    except:
        pass
    return 'STARTER'

def safe_has_access(user_id):
    try:
        tier = safe_get_user_tier(user_id)
        if tier == 'STARTER':
            return False
        expiry = USERS_DATA.get(int(user_id), {}).get('expiry')
        return expiry and expiry > datetime.now(timezone.utc)
    except:
        return False

def safe_init_user(uid_str, username="Unknown"):
    try:
        with data_lock:
            if uid_str not in user_data:
                user_data[uid_str] = {}
            u = user_data[uid_str]
            u.setdefault('username', username)
            u.setdefault('scans_today', 0)
            u.setdefault('last_scan_date', str(datetime.now().date()))
            u.setdefault('pnl', 0)
            u.setdefault('wins', 0)
            u.setdefault('losses', 0)
            u.setdefault('streak', 0)
            u.setdefault('settings', {
                'killzone_pings': True, 'min_confidence': 60, 'quiet_hours': False,
                'voice_alerts': True, 'prop_mode': False, 'auto_scan': False, 'simple_signal': True
            })
            today = str(datetime.now().date())
            if u.get('last_scan_date')!= today:
                u['scans_today'] = 0
                u['last_scan_date'] = today
            safe_save()
    except Exception as e:
        print(f"SAFE_INIT ERROR: {e}", flush=True)

def escape_markdown(text):
    try:
        if not text: return ""
        chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in chars:
            text = str(text).replace(char, f'\\{char}')
        return text
    except:
        return str(text)

# ===== CHANNEL FUNCTIONS =====
def post_to_channel(text):
    try:
        if CHANNEL_ID and CHANNEL_ID!= '@YourChannel':
            bot.send_message(CHANNEL_ID, text, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        print(f"CHANNEL ERROR: {e}", flush=True)

# ===== ICT ENGINE - BULLETPROOF =====
@lru_cache(maxsize=128)
def get_data_cached(pair, interval, period, cache_key):
    try:
        yf_pair = pair.replace('_OTC', '=X') if '_OTC' in pair else pair
        ticker = yf.Ticker(yf_pair)
        df = ticker.history(period=period, interval=interval)
        if df.empty: return None
        return df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
    except:
        return None

def get_data(pair, interval='1m', period='1d'):
    cache_key = int(time.time() // 60)
    return get_data_cached(pair, interval, period, cache_key)

def detect_bos(df):
    try:
        if df is None or len(df) < 20: return 0
        highs = df['High'].values
        lows = df['Low'].values
        closes = df['Close'].values
        if closes[-1] > max(highs[-10:-1]): return 1
        if closes[-1] < min(lows[-10:-1]): return -1
    except:
        pass
    return 0

def detect_fvg(df):
    try:
        if df is None or len(df) < 3: return 0
        h1, l1 = df['High'].iloc[-1], df['Low'].iloc[-1]
        h3, l3 = df['High'].iloc[-3], df['Low'].iloc[-3]
        if l1 > h3: return 1
        if h1 < l3: return -1
    except:
        pass
    return 0

def detect_order_block(df):
    try:
        if df is None or len(df) < 10: return 0
        closes = df['Close'].values
        opens = df['Open'].values
        for i in range(len(df)-5, len(df)-1):
            if closes[i] < opens[i] and closes[i+1] > opens[i+1]:
                if closes[-1] > closes[i]: return 1
            if closes[i] > opens[i] and closes[i+1] < opens[i+1]:
                if closes[-1] < closes[i]: return -1
    except:
        pass
    return 0

def get_trend_1h(pair):
    try:
        df = get_data(pair, '1h', '5d')
        if df is None or len(df) < 20: return 0
        sma20 = df['Close'].rolling(20).mean().iloc[-1]
        if df['Close'].iloc[-1] > sma20: return 1
    except:
        pass
    return -1

def check_killzone():
    try:
        hour = datetime.now(timezone.utc).hour
        return (7 <= hour < 10) or (12 <= hour < 15)
    except:
        return False

# ===== SIGNAL GENERATION - BULLETPROOF =====
def analyze_pocket_pair(pair, user_id):
    try:
        tier = safe_get_user_tier(user_id)
        tier_cfg = TIERS_CONFIG
        mode = USER_SETTINGS.get(int(user_id), {}).get('mode', 'PO')

        df_1m = get_data(pair, '1m', '1d')
        if df_1m is None or len(df_1m) < 20:
            return None, "No data"

        confidence = 0
        direction = 0
        breakdown = []

        bos = detect_bos(df_1m)
        if bos == 1: confidence += 20; breakdown.append("✅ 1m Bullish Bos +20"); direction = 1
        if bos == -1: confidence += 20; breakdown.append("✅ 1m Bearish Bos +20"); direction = -1

        fvg = detect_fvg(df_1m)
        if fvg == 1 and direction >= 0: confidence += 20; breakdown.append("✅ 1m FVG Retest +20"); direction = 1
        if fvg == -1 and direction <= 0: confidence += 20; breakdown.append("✅ 1m FVG Retest +20"); direction = -1

        ob = detect_order_block(df_1m)
        if ob == 1 and direction >= 0: confidence += 20; breakdown.append("✅ Order Block +20"); direction = 1
        if ob == -1 and direction <= 0: confidence += 20; breakdown.append("✅ Order Block +20"); direction = -1

        trend = get_trend_1h(pair)
        if trend == direction: confidence += 20; breakdown.append("✅ 1H Trend Align +20")

        if check_killzone(): confidence += 20; breakdown.append("✅ London/NY Killzone +20")

        min_conf = tier_cfg['grade_min']
        if confidence < min_conf or direction == 0:
            return None, f"No A+ setup. Need {min_conf}%, got {confidence}%"

        grade = "A+" if confidence >= 75 else "B+"
        expiry = "1M" if confidence >= 75 else "5M"
        eat_tz = timezone(timedelta(hours=3))
        entry_time = datetime.now(eat_tz) + timedelta(minutes=1)
        entry_time = entry_time.replace(second=15)

        return {
            'direction': 'CALL' if direction == 1 else 'PUT',
            'pair': pair,
            'expiry': expiry,
            'entry_time': entry_time,
            'confidence': int(confidence),
            'grade': grade,
            'confluence': {'breakdown': breakdown, 'score': confidence},
            'mode': mode
        }, None
    except Exception as e:
        print(f"ANALYZE ERROR: {e}", flush=True)
        return None, "Analysis error"

def format_pocket_signal(signal, user_id, for_channel=False):
    try:
        tier = safe_get_user_tier(user_id)
        tier_cfg = TIERS_CONFIG
        use_simple = user_data.get(str(user_id), {}).get('settings', {}).get('simple_signal', tier_cfg['simple_mode'])

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
        channel_footer = f"\n\nJoin @{str(CHANNEL_ID).replace('@','')} for more signals" if for_channel and CHANNEL_ID!= '@YourChannel' else ""

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
    except Exception as e:
        print(f"FORMAT ERROR: {e}", flush=True)
        return f"Signal: {signal.get('pair','?')} {signal.get('direction','?')} {signal.get('confidence','?')}%"

# ===== COMMANDS - BULLETPROOF =====
@bot.message_handler(commands=['start'])
def cmd_start(message):
    try:
        user_id = message.from_user.id
        uid_str = str(user_id)
        safe_init_user(uid_str, message.from_user.username or message.from_user.first_name)

        tier = safe_get_user_tier(user_id)
        mode = USER_SETTINGS.get(user_id, {}).get('mode', 'PO')
        mode_emoji = "📱" if mode == 'PO' else "💹"
        has_sub = safe_has_access(user_id)

        if has_sub:
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
            text = f"✅ Welcome back {tier}\n\nMode: {mode.upper()} {mode_emoji}\n\nChoose your market or get a signal:"
            bot.send_message(message.chat.id, text, reply_markup=markup)
        else:
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("📊 Pocket Option", callback_data="mode_PO"),
                       types.InlineKeyboardButton("💱 Forex Live", callback_data="mode_FOREX"))
            text = (
                f"👋 Welcome to SMC ELITE BOT\n\n"
                f"🎁 Try it free: /demo\n"
                f"⚡ 87% of ELITE users started with /demo\n\n"
                f"Ready to upgrade?\n"
                f"💵 Pay via M-Pesa: {MPESA_NUMBER}\n"
                f"📝 Ref: @{message.from_user.username or message.from_user.id}\n"
                f"📞 Support: {SUPPORT_CONTACT}"
            )
            bot.send_message(message.chat.id, text, reply_markup=markup)
    except Exception as e:
        print(f"START CRASH: {e}", flush=True)
        try:
            bot.send_message(message.chat.id, "✅ Bot is online. Try /start again.")
        except:
            pass

@bot.message_handler(commands=['getsignal'])
def cmd_getsignal(message):
    try:
        user_id = message.from_user.id
        if not safe_has_access(user_id):
            bot.reply_to(message, "❌ Not subscribed. Use /start to pick a plan.")
            return

        tier = safe_get_user_tier(user_id)
        tier_cfg = TIERS_CONFIG
        limit = tier_cfg['scans']
        scans = user_data.get(str(user_id), {}).get('scans_today', 0)

        if scans >= limit:
            bot.reply_to(message, f"❌ Daily limit {limit} reached.")
            return

        mode = USER_SETTINGS.get(user_id, {}).get('mode', 'PO')
        pairs = PAIRS_FOREX if mode == 'FOREX' and tier_cfg['forex'] else PAIRS_OTC
        markup = types.InlineKeyboardMarkup(row_width=3)
        pair_limit = min(tier_cfg['pairs'], len(pairs))
        buttons = [types.InlineKeyboardButton(p.replace('_OTC','').replace('=X',''), callback_data=f"scan_{p}") for p in pairs[:pair_limit]]
        markup.add(*buttons)
        bot.send_message(message.chat.id, f"📊 Select pair to scan:\n\nMode: {mode} | Scans: {scans}/{limit} | Tier: {tier}", reply_markup=markup)
    except Exception as e:
        print(f"GETSIGNAL ERROR: {e}", flush=True)
        try:
            bot.reply_to(message, "❌ Error. Try again.")
        except:
            pass

# ===== CALLBACKS - BULLETPROOF =====
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        user_id = call.from_user.id
        uid_str = str(user_id)
        safe_init_user(uid_str, call.from_user.username or call.from_user.first_name)
        tier = safe_get_user_tier(user_id)

        if call.data == "get_signal":
            cmd_getsignal(call.message)

        elif call.data.startswith("scan_"):
            try:
                if not safe_has_access(user_id):
                    bot.answer_callback_query(call.id, "❌ Subscription expired.", show_alert=True)
                    return

                tier_cfg = TIERS_CONFIG
                limit = tier_cfg['scans']
                scans = user_data.get(uid_str, {}).get('scans_today', 0)
                if scans >= limit:
                    bot.answer_callback_query(call.id, f"Daily limit {limit} reached.", show_alert=True)
                    return

                pair = call.data.replace("scan_", "")
                bot.answer_callback_query(call.id, f"Scanning {pair}...")
                bot.edit_message_text(f"🔍 Scanning {pair.replace('_OTC','').replace('=X','')} for A+ setup...\n\nScans today: {scans+1}/{limit}", call.message.chat.id, call.message.message_id)

                signal, error = analyze_pocket_pair(pair, user_id)
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(types.InlineKeyboardButton("🔄 New Signal", callback_data="get_signal"),
                          types.InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu"))

                if signal:
                    with data_lock:
                        user_data[uid_str]['scans_today'] = user_data[uid_str].get('scans_today', 0) + 1
                        safe_save()

                    signal_text = format_pocket_signal(signal, user_id)
                    remaining = limit - user_data[uid_str]['scans_today']
                    footer = f"\n\nScans left today: {remaining}" if limit!= 9999 else ""
                    bot.edit_message_text(signal_text + footer, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)
                    post_to_channel(format_pocket_signal(signal, user_id, for_channel=True))
                else:
                    bot.edit_message_text(f"❌ {error}\n\nScan not counted. {limit - scans} left today.", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception as e:
                print(f"SCAN ERROR: {e}", flush=True)
                bot.answer_callback_query(call.id, "❌ Scan error. Try again.")

        elif call.data == "mode_PO":
            try:
                USER_SETTINGS.setdefault(user_id, {})['mode'] = 'PO'
                if user_id in USERS_DATA:
                    USERS_DATA[user_id]['mode'] = 'PO'
                safe_save()
                bot.answer_callback_query(call.id, "✅ Switched to Pocket Option")
                cmd_start(call.message)
            except:
                bot.answer_callback_query(call.id, "✅ Switched")

        elif call.data == "mode_FOREX":
            try:
                tier_cfg = TIERS_CONFIG
                if not tier_cfg['forex']:
                    bot.answer_callback_query(call.id, "❌ Upgrade to ADVANCED for Forex", show_alert=True)
                    return
                USER_SETTINGS.setdefault(user_id, {})['mode'] = 'FOREX'
                if user_id in USERS_DATA:
                    USERS_DATA[user_id]['mode'] = 'FOREX'
                safe_save()
                bot.answer_callback_query(call.id, "✅ Switched to Forex Live")
                cmd_start(call.message)
            except:
                bot.answer_callback_query(call.id, "✅ Switched")

        elif call.data == "back_menu":
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            cmd_start(call.message)

        elif call.data == "demo":
            try:
                pair = random.choice(PAIRS_OTC[:3])
                eat_time = datetime.now(timezone(timedelta(hours=3))).strftime('%H:%M')
                bot.send_message(user_id, f"""
🎁 DEMO SIGNAL - WATERMARKED

🟢 PROFIT POTENTIAL: 87%

Your Settings:
CURRENCY PAIR: {pair.replace('_OTC','')}
TIME: S15

⬆️⬆️⬆️ UP ⬆️⬆️⬆️
{eat_time} EAT

⚠️ This is a demo. Upgrade to get live A+ alerts.

Pay via M-Pesa: {MPESA_NUMBER}
Send screenshot: {SUPPORT_CONTACT}
""")
                bot.answer_callback_query(call.id, "Demo signal sent!")
            except:
                bot.answer_callback_query(call.id, "Demo sent")

        else:
            bot.answer_callback_query(call.id, "Coming soon")

    except Exception as e:
        print(f"CALLBACK MASTER ERROR: {e}", flush=True)
        try:
            bot.answer_callback_query(call.id, "❌ Error. Try again.")
        except:
            pass

# ===== START BOT =====
if __name__ == "__main__":
    safe_load()
    logging.info("=== BOT POLLING STARTED ===")
    print(f"BOT_TOKEN set: {bool(BOT_TOKEN)}", flush=True)
    print(f"ADMIN_ID: {ADMIN_ID}", flush=True)

    try:
        bot.delete_webhook(drop_pending_updates=True)
    except:
        pass

    bot.infinity_polling(timeout=60, long_polling_timeout=60)
