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
import sys

sys.stdout.reconfigure(line_buffering=True)

# ===== CONFIG FROM ENV =====
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER', '0700000000')
SUPPORT_CONTACT = os.getenv('SUPPORT_HANDLE', '@Support')
CHANNEL_ID = os.getenv('CHANNEL_ID', '')

if not BOT_TOKEN:
    print("FATAL: BOT_TOKEN missing in environment", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# ===== FILES =====
USER_DATA_FILE = 'user_data.json'
USERS_DB_FILE = 'users_db.json'
RESULTS_FILE = 'results.json'

# ===== GLOBALS =====
USER_DATA = {}
USERS_DB = {}
USER_SETTINGS = {}
RESULTS_DATA = []
DATA_LOCK = threading.Lock()

# ===== PAIRS =====
PAIRS_OTC = [
    'EURUSD_OTC','GBPUSD_OTC','USDJPY_OTC','AUDUSD_OTC','USDCAD_OTC','EURGBP_OTC',
    'EURJPY_OTC','GBPJPY_OTC','NZDUSD_OTC','USDCHF_OTC','EURAUD_OTC','GBPAUD_OTC',
    'EURCHF_OTC','GBPCHF_OTC','AUDJPY_OTC','CADJPY_OTC','NZDJPY_OTC','CHFJPY_OTC'
]

PAIRS_FOREX = [
    'EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X','USDCAD=X','EURGBP=X',
    'EURJPY=X','GBPJPY=X','NZDUSD=X','USDCHF=X','AUDJPY=X','CADJPY=X'
]

# ===== TIERS =====
TIERS = {
    'STARTER': {'pairs': 1, 'scans': 5, 'charts': False, 'forex': False, 'min_conf': 65, 'price': 'Free'},
    'ADVANCED': {'pairs': 7, 'scans': 20, 'charts': False, 'forex': True, 'min_conf': 70, 'price': 'Ksh 2,500'},
    'ELITE': {'pairs': 99, 'scans': 999, 'charts': True, 'forex': True, 'min_conf': 75, 'price': 'Ksh 5,000'},
    'INSTITUTIONAL': {'pairs': 99, 'scans': 9999, 'charts': True, 'forex': True, 'min_conf': 75, 'price': 'Ksh 10,000'}
}

# ===== DB LOAD/SAVE =====
def load_all():
    global USER_DATA, USERS_DB, RESULTS_DATA
    try:
        if os.path.exists(USER_DATA_FILE):
            with open(USER_DATA_FILE, 'r') as f:
                USER_DATA = json.load(f)
        if os.path.exists(USERS_DB_FILE):
            with open(USERS_DB_FILE, 'r') as f:
                data = json.load(f)
                for uid, u in data.items():
                    if u.get('expiry'):
                        try:
                            u['expiry'] = datetime.fromisoformat(u['expiry'])
                        except:
                            u['expiry'] = None
                    USERS_DB[int(uid)] = u
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, 'r') as f:
                RESULTS_DATA = json.load(f)
        print("DB LOADED", flush=True)
    except Exception as e:
        print(f"LOAD ERROR: {e}", flush=True)

def save_user_data():
    try:
        with DATA_LOCK:
            with open(USER_DATA_FILE, 'w') as f:
                json.dump(USER_DATA, f, indent=2, default=str)
    except Exception as e:
        print(f"SAVE USER_DATA ERROR: {e}", flush=True)

def save_users_db():
    try:
        with DATA_LOCK:
            out = {}
            for uid, u in USERS_DB.items():
                tmp = u.copy()
                if tmp.get('expiry'):
                    tmp['expiry'] = tmp['expiry'].isoformat()
                out[str(uid)] = tmp
            with open(USERS_DB_FILE, 'w') as f:
                json.dump(out, f, indent=2)
    except Exception as e:
        print(f"SAVE USERS_DB ERROR: {e}", flush=True)

def save_results():
    try:
        with DATA_LOCK:
            with open(RESULTS_FILE, 'w') as f:
                json.dump(RESULTS_DATA, f, indent=2, default=str)
    except Exception as e:
        print(f"SAVE RESULTS ERROR: {e}", flush=True)

# ===== USER HELPERS =====
def init_user(uid, username="Unknown"):
    uid_str = str(uid)
    with DATA_LOCK:
        if uid_str not in USER_DATA:
            USER_DATA[uid_str] = {
                'username': username,
                'scans_today': 0,
                'last_scan_date': str(datetime.now().date()),
                'wins': 0,
                'losses': 0,
                'pnl': 0.0,
                'streak': 0,
                'settings': {
                    'killzone_pings': True,
                    'quiet_hours': False,
                    'simple_signal': True,
                    'prop_mode': False,
                    'min_confidence': 60
                }
            }
        else:
            USER_DATA[uid_str]['username'] = username

        today = str(datetime.now().date())
        if USER_DATA[uid_str].get('last_scan_date')!= today:
            USER_DATA[uid_str]['scans_today'] = 0
            USER_DATA[uid_str]['last_scan_date'] = today
        save_user_data()

def get_tier(uid):
    try:
        uid = int(uid)
        if uid in USERS_DB:
            exp = USERS_DB[uid].get('expiry')
            if exp and isinstance(exp, datetime) and exp > datetime.now(timezone.utc):
                return USERS_DB[uid].get('tier', 'STARTER')
    except:
        pass
    return 'STARTER'

def has_access(uid):
    return get_tier(uid)!= 'STARTER'

def can_scan(uid):
    tier = get_tier(uid)
    limit = TIERS[tier]['scans']
    scans = USER_DATA.get(str(uid), {}).get('scans_today', 0)
    return scans < limit, scans, limit

def is_quiet_hours(uid):
    try:
        if not USER_DATA.get(str(uid), {}).get('settings', {}).get('quiet_hours', False):
            return False
        h = datetime.now(timezone(timedelta(hours=3))).hour
        return h >= 22 or h < 7
    except:
        return False

# ===== MARKET ENGINE =====
def get_df(pair, interval='1m', period='1d'):
    try:
        p = pair.replace('_OTC', '=X') if '_OTC' in pair else pair
        df = yf.Ticker(p).history(period=period, interval=interval, prepost=False)
        return df[['Open','High','Low','Close']].dropna() if not df.empty else None
    except:
        return None

def bos(df):
    try:
        if df is None or len(df) < 20: return 0
        c = df['Close'].values
        h = df['High'].values
        l = df['Low'].values
        if c[-1] > h[-15:-1].max(): return 1
        if c[-1] < l[-15:-1].min(): return -1
    except:
        pass
    return 0

def fvg(df):
    try:
        if df is None or len(df) < 3: return 0
        if df['Low'].iloc[-1] > df['High'].iloc[-3]: return 1
        if df['High'].iloc[-1] < df['Low'].iloc[-3]: return -1
    except:
        pass
    return 0

def ob(df):
    try:
        if df is None or len(df) < 10: return 0
        c = df['Close'].values
        o = df['Open'].values
        for i in range(len(df)-6, len(df)-2):
            if c[i] < o[i] and c[i+1] > o[i+1] and c[-1] > c[i]: return 1
            if c[i] > o[i] and c[i+1] < o[i+1] and c[-1] < c[i]: return -1
    except:
        pass
    return 0

def trend_1h(pair):
    try:
        df = get_df(pair, '1h', '5d')
        if df is None or len(df) < 20: return 0
        sma = df['Close'].rolling(20).mean().iloc[-1]
        return 1 if df['Close'].iloc[-1] > sma else -1
    except:
        return 0

def killzone_active():
    h = datetime.now(timezone.utc).hour
    return (7 <= h < 10) or (12 <= h < 15)

# ===== SIGNAL LOGIC =====
def analyze_pair(pair, uid):
    try:
        tier = get_tier(uid)
        min_conf = TIERS[tier]['min_conf']
        mode = USER_SETTINGS.get(uid, {}).get('mode', 'PO')

        df = get_df(pair, '1m', '1d')
        if df is None or len(df) < 20:
            return None, "No market data"

        conf = 0
        direction = 0
        breakdown = []

        b = bos(df)
        if b == 1: conf += 20; direction = 1; breakdown.append("✅ 1m Bullish BOS +20")
        if b == -1: conf += 20; direction = -1; breakdown.append("✅ 1m Bearish BOS +20")

        f = fvg(df)
        if f == 1 and direction >= 0: conf += 20; direction = 1; breakdown.append("✅ 1m FVG +20")
        if f == -1 and direction <= 0: conf += 20; direction = -1; breakdown.append("✅ 1m FVG +20")

        o = ob(df)
        if o == 1 and direction >= 0: conf += 20; direction = 1; breakdown.append("✅ Order Block +20")
        if o == -1 and direction <= 0: conf += 20; direction = -1; breakdown.append("✅ Order Block +20")

        t = trend_1h(pair)
        if t == direction and t!= 0: conf += 20; breakdown.append("✅ 1H Trend Align +20")

        if killzone_active(): conf += 20; breakdown.append("✅ Killzone +20")

        if conf < min_conf or direction == 0:
            return None, f"No A+ setup. Need {min_conf}%, got {conf}%"

        eat = timezone(timedelta(hours=3))
        entry = (datetime.now(eat) + timedelta(minutes=1)).replace(second=15, microsecond=0)

        return {
            'pair': pair,
            'direction': 'CALL' if direction == 1 else 'PUT',
            'confidence': conf,
            'entry': entry,
            'expiry': '1M',
            'grade': 'A+' if conf >= 75 else 'B+',
            'breakdown': breakdown,
            'mode': mode
        }, None
    except Exception as e:
        print(f"ANALYZE ERROR: {e}", flush=True)
        return None, "Analysis error"

def format_signal(sig, uid, channel=False):
    try:
        simple = USER_DATA.get(str(uid), {}).get('settings', {}).get('simple_signal', True)
        tier = get_tier(uid)

        if simple and not channel:
            arrow = "⬆️⬆️⬆️ UP ⬆️⬆️⬆️" if sig['direction'] == 'CALL' else "⬇️⬇️⬇️ DOWN ⬇️⬇️⬇️"
            return f"""
🟢 PROFIT POTENTIAL: {sig['confidence']}%

CURRENCY PAIR: {sig['pair'].replace('_OTC','').replace('=X','')}
TIME: S15

{arrow}
{sig['entry'].strftime('%H:%M')} EAT
"""

        tag = "👑 ELITE A+" if tier == 'ELITE' else "🌍 INSTITUTIONAL" if tier == 'INSTITUTIONAL' else "💎 ADVANCED A+"
        arrow = "⬆️ CALL" if sig['direction'] == 'CALL' else "⬇️ PUT"
        conf_txt = "\n".join(sig['breakdown'])
        footer = f"\n\nJoin {CHANNEL_ID}" if channel and CHANNEL_ID else ""

        return f"""
{tag}

Pair: {sig['pair'].replace('_OTC','').replace('=X','')}
Direction: {arrow}
Entry: {sig['entry'].strftime('%H:%M:%S')} EAT
Expiry: {sig['expiry']}
Mode: {sig['mode']}

Grade: {sig['grade']} ({sig['confidence']}/100)
Confluence:
{conf_txt}

⚠️ Enter at exact second. Risk 1-2%.{footer}
"""
    except:
        return f"{sig['pair']} {sig['direction']} {sig['confidence']}%"

# ===== CHANNEL =====
def post_channel(text):
    try:
        if CHANNEL_ID:
            bot.send_message(CHANNEL_ID, text, disable_web_page_preview=True)
    except Exception as e:
        print(f"CHANNEL ERROR: {e}", flush=True)

def broadcast_win(pair, direction, conf, entry_time):
    try:
        txt = f"✅ WIN\n\n{pair.replace('_OTC','').replace('=X','')} {direction}\nEntry: {entry_time.strftime('%H:%M:%S')} EAT\nConfidence: {conf}%"
        post_channel(txt)
    except:
        pass

# ===== COMMANDS =====
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    try:
        uid = msg.from_user.id
        init_user(uid, msg.from_user.username or msg.from_user.first_name)
        tier = get_tier(uid)
        mode = USER_SETTINGS.get(uid, {}).get('mode', 'PO')
        print(f"START {uid} {tier} {mode}", flush=True)

        if has_access(uid):
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("📊 Pocket Option", callback_data="mode_po"),
                types.InlineKeyboardButton("💱 Forex Live", callback_data="mode_forex"),
                types.InlineKeyboardButton("📈 Get Signal", callback_data="get_signal"),
                types.InlineKeyboardButton("📊 My Stats", callback_data="stats"),
                types.InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                types.InlineKeyboardButton("📚 Help", callback_data="help")
            )
            if uid == ADMIN_ID:
                kb.add(types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin"))
            txt = f"✅ Welcome back {tier}\n\nMode: {mode}\n\nChoose option:"
        else:
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("📊 Pocket Option", callback_data="mode_po"),
                types.InlineKeyboardButton("💱 Forex Live", callback_data="mode_forex"),
                types.InlineKeyboardButton("🎁 Free Demo", callback_data="demo")
            )
            txt = f"👋 SMC ELITE BOT\n\n🎁 Try /demo free\n\nUpgrade:\n💵 M-Pesa: {MPESA_NUMBER}\n📞 {SUPPORT_CONTACT}"

        bot.send_message(msg.chat.id, txt, reply_markup=kb)
    except Exception as e:
        print(f"START CMD ERROR: {e}", flush=True)
        try:
            bot.send_message(msg.chat.id, "Bot online. Try again.")
        except:
            pass

@bot.message_handler(commands=['demo'])
def cmd_demo(msg):
    try:
        pair = random.choice(PAIRS_OTC[:4])
        eat = timezone(timedelta(hours=3))
        t = datetime.now(eat).strftime('%H:%M')
        txt = f"""
🎁 DEMO SIGNAL

PAIR: {pair.replace('_OTC','')}
TIME: S15

⬆️⬆️⬆️ UP ⬆️⬆️⬆️
{t} EAT

This is demo. Upgrade for live A+ signals.
M-Pesa: {MPESA_NUMBER}
"""
        bot.send_message(msg.chat.id, txt)
    except Exception as e:
        print(f"DEMO ERROR: {e}", flush=True)

@bot.message_handler(commands=['getsignal'])
def cmd_getsignal(msg):
    try:
        uid = msg.from_user.id
        if not has_access(uid):
            bot.reply_to(msg, "❌ Subscribe first. /start")
            return
        if is_quiet_hours(uid):
            bot.reply_to(msg, "🌙 Quiet hours active")
            return

        allowed, scans, limit = can_scan(uid)
        if not allowed:
            bot.reply_to(msg, f"❌ Daily limit {limit} reached")
            return

        tier = get_tier(uid)
        mode = USER_SETTINGS.get(uid, {}).get('mode', 'PO')
        pairs = PAIRS_FOREX if mode == 'FOREX' and TIERS[tier]['forex'] else PAIRS_OTC

        kb = types.InlineKeyboardMarkup(row_width=3)
        pair_limit = min(TIERS[tier]['pairs'], len(pairs))
        btns = [types.InlineKeyboardButton(p.replace('_OTC','').replace('=X',''), callback_data=f"scan_{p}") for p in pairs[:pair_limit]]
        kb.add(*btns)
        bot.send_message(msg.chat.id, f"📊 Select pair:\n\nMode: {mode} | Scans: {scans}/{limit} | Tier: {tier}", reply_markup=kb)
    except Exception as e:
        print(f"GETSIGNAL ERROR: {e}", flush=True)

@bot.message_handler(commands=['adduser'])
def cmd_adduser(msg):
    try:
        if msg.from_user.id!= ADMIN_ID:
            return
        parts = msg.text.split()
        if len(parts) < 3:
            bot.reply_to(msg, "Usage: /adduser USER_ID TIER")
            return
        uid = int(parts[1])
        tier = parts[2].upper()
        if tier not in TIERS:
            bot.reply_to(msg, "Invalid tier. Use: STARTER, ADVANCED, ELITE, INSTITUTIONAL")
            return
        USERS_DB[uid] = {
            'tier': tier,
            'expiry': datetime.now(timezone.utc) + timedelta(days=30),
            'expiry_notified': False
        }
        save_users_db()
        bot.reply_to(msg, f"✅ Added {uid} as {tier} for 30 days")
    except Exception as e:
        print(f"ADDUSER ERROR: {e}", flush=True)

# ===== CALLBACKS =====
@bot.callback_query_handler(func=lambda c: True)
def callback_all(call):
    try:
        uid = call.from_user.id
        init_user(uid, call.from_user.username or call.from_user.first_name)
        tier = get_tier(uid)

        if call.data == "get_signal":
            cmd_getsignal(call.message)

        elif call.data.startswith("scan_"):
            if not has_access(uid):
                bot.answer_callback_query(call.id, "❌ Subscription expired", show_alert=True)
                return
            if is_quiet_hours(uid):
                bot.answer_callback_query(call.id, "🌙 Quiet hours", show_alert=True)
                return
            allowed, scans, limit = can_scan(uid)
            if not allowed:
                bot.answer_callback_query(call.id, f"Limit {limit} reached", show_alert=True)
                return

            pair = call.data.replace("scan_", "")
            bot.answer_callback_query(call.id, f"Scanning {pair}...")
            bot.edit_message_text(f"🔍 Scanning {pair.replace('_OTC','').replace('=X','')}...\n\nScans: {scans+1}/{limit}", call.message.chat.id, call.message.message_id)

            sig, err = analyze_pair(pair, uid)
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("🔄 New Signal", callback_data="get_signal"),
                types.InlineKeyboardButton("🔙 Menu", callback_data="back")
            )

            if sig:
                with DATA_LOCK:
                    USER_DATA[str(uid)]['scans_today'] += 1
                    save_user_data()
                txt = format_signal(sig, uid)
                remaining = limit - USER_DATA[str(uid)]['scans_today']
                footer = f"\n\nScans left: {remaining}" if limit < 999 else ""
                bot.edit_message_text(txt + footer, call.message.chat.id, call.message.message_id, reply_markup=kb)
                post_channel(format_signal(sig, uid, channel=True))
                if sig['confidence'] >= 80:
                    threading.Timer(65, broadcast_win, args=[sig['pair'], sig['direction'], sig['confidence'], sig['entry']]).start()
            else:
                bot.edit_message_text(f"❌ {err}\n\nScan not counted. {limit-scans} left.", call.message.chat.id, call.message.message_id, reply_markup=kb)

        elif call.data == "mode_po":
            USER_SETTINGS.setdefault(uid, {})['mode'] = 'PO'
            bot.answer_callback_query(call.id, "✅ Pocket Option mode")
            cmd_start(call.message)

        elif call.data == "mode_forex":
            if not TIERS[tier]['forex']:
                bot.answer_callback_query(call.id, "❌ Upgrade to ADVANCED for Forex", show_alert=True)
                return
            USER_SETTINGS.setdefault(uid, {})['mode'] = 'FOREX'
            bot.answer_callback_query(call.id, "✅ Forex mode")
            cmd_start(call.message)

        elif call.data == "stats":
            u = USER_DATA.get(str(uid), {})
            wr = (u.get('wins', 0) / max(1, u.get('wins', 0) + u.get('losses', 0))) * 100
            txt = f"""
📊 YOUR STATS

Tier: {tier}
Scans Today: {u.get('scans_today', 0)}
Wins: {u.get('wins', 0)} ✅
Losses: {u.get('losses', 0)} ❌
Win Rate: {wr:.1f}%
Net P&L: {u.get('pnl', 0):+.2f}
Streak: {u.get('streak', 0)}
"""
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("🔙 Menu", callback_data="back"))
            bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data == "settings":
            s = USER_DATA.get(str(uid), {}).get('settings', {})
            kz = "ON ✅" if s.get('killzone_pings', True) else "OFF ❌"
            simple = "ON ✅" if s.get('simple_signal', True) else "OFF ❌"
            quiet = "ON ✅" if s.get('quiet_hours', False) else "OFF ❌"
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(
                types.InlineKeyboardButton(f"Killzone: {kz}", callback_data="toggle_kz"),
                types.InlineKeyboardButton(f"Simple Mode: {simple}", callback_data="toggle_simple"),
                types.InlineKeyboardButton(f"Quiet Hours: {quiet}", callback_data="toggle_quiet"),
                types.InlineKeyboardButton("🔙 Menu", callback_data="back")
            )
            bot.edit_message_text("⚙️ SETTINGS\n\nToggle preferences:", call.message.chat.id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data == "toggle_kz":
            with DATA_LOCK:
                current = USER_DATA[str(uid)]['settings'].get('killzone_pings', True)
                USER_DATA[str(uid)]['settings']['killzone_pings'] = not current
                save_user_data()
            bot.answer_callback_query(call.id, f"Killzone {'OFF' if current else 'ON'}")
            call.data = "settings"
            callback_all(call)

        elif call.data == "toggle_simple":
            with DATA_LOCK:
                current = USER_DATA[str(uid)]['settings'].get('simple_signal', True)
                USER_DATA[str(uid)]['settings']['simple_signal'] = not current
                save_user_data()
            bot.answer_callback_query(call.id, f"Simple {'OFF' if current else 'ON'}")
            call.data = "settings"
            callback_all(call)

        elif call.data == "toggle_quiet":
            with DATA_LOCK:
                current = USER_DATA[str(uid)]['settings'].get('quiet_hours', False)
                USER_DATA[str(uid)]['settings']['quiet_hours'] = not current
                save_user_data()
            bot.answer_callback_query(call.id, f"Quiet Hours {'OFF' if current else 'ON'}")
            call.data = "settings"
            callback_all(call)

        elif call.data == "help":
            txt = f"""
📚 HELP

/start - Main menu
/getsignal - Scan for setups
/demo - Free demo

How it works:
1. Bot scans for BOS + FVG + Order Block
2. Only sends if A+ >75% confidence
3. Enter at exact second shown

Support: {SUPPORT_CONTACT}
M-Pesa: {MPESA_NUMBER}

Not financial advice. Risk 1-2%.
"""
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("🔙 Menu", callback_data="back"))
            bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data == "admin":
            if uid!= ADMIN_ID:
                bot.answer_callback_query(call.id, "❌ Admin only", show_alert=True)
                return
            txt = f"""
🔧 ADMIN PANEL

Users: {len(USERS_DB)}
Signals Today: {len(RESULTS_DATA)}

Commands:
/adduser USER_ID TIER
"""
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("🔙 Menu", callback_data="back"))
            bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data == "back":
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            cmd_start(call.message)

        elif call.data == "demo":
            cmd_demo(call.message)
            bot.answer_callback_query(call.id, "Demo sent")

    except Exception as e:
        print(f"CALLBACK ERROR: {e}", flush=True)
        try:
            bot.answer_callback_query(call.id, "❌ Error. Try again.")
        except:
            pass

# ===== SCHEDULER =====
def run_scheduler():
    schedule.every().day.at("00:00").do(reset_daily_scans)
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            print(f"SCHEDULER ERROR: {e}", flush=True)

def reset_daily_scans():
    try:
        with DATA_LOCK:
            for uid in USER_DATA:
                USER_DATA[uid]['scans_today'] = 0
                USER_DATA[uid]['last_scan_date'] = str(datetime.now().date())
            save_user_data()
        print("DAILY RESET DONE", flush=True)
    except Exception as e:
        print(f"RESET ERROR: {e}", flush=True)

# ===== START =====
if __name__ == "__main__":
    print("=== BOT STARTING ===", flush=True)
    load_all()

    sched = threading.Thread(target=run_scheduler, daemon=True)
    sched.start()
    print("=== SCHEDULER STARTED ===", flush=True)

    try:
        bot.delete_webhook(drop_pending_updates=True)
        print("=== WEBHOOK DELETED ===", flush=True)
    except Exception as e:
        print(f"WEBHOOK ERROR: {e}", flush=True)

    print("=== POLLING STARTED ===", flush=True)
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
