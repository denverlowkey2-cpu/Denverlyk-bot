import sys
print("=== BOT BOOT SEQUENCE START ===", flush=True)

try:
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
    print("1. All imports OK", flush=True)
except Exception as e:
    print(f"FATAL IMPORT: {e}", flush=True)
    sys.exit(1)

# ===== CONFIG =====
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER', '0700000000')
SUPPORT_CONTACT = os.getenv('SUPPORT_HANDLE', '@Support')
CHANNEL_ID = os.getenv('CHANNEL_ID', '')

if not BOT_TOKEN or ':' not in BOT_TOKEN:
    print("FATAL: BOT_TOKEN invalid", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
print("2. Bot object created", flush=True)

# ===== DATA =====
USER_DATA_FILE = 'user_data.json'
USERS_DB_FILE = 'users_db.json'
SETTINGS_FILE = 'settings.json'
USER_DATA = {}
USERS_DB = {}
SETTINGS = {}
DATA_LOCK = threading.Lock()

PAIRS_OTC = ['EURUSD_OTC','GBPUSD_OTC','USDJPY_OTC','AUDUSD_OTC','USDCAD_OTC','EURGBP_OTC','EURJPY_OTC','GBPJPY_OTC']
PAIRS_FOREX = ['EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X','USDCAD=X','EURGBP=X','EURJPY=X','GBPJPY=X']
TIMEFRAMES = ['1m', '5m', '15m']

TIERS = {
    'STARTER': {'pairs': 1, 'scans': 5, 'min_conf': 65},
    'ADVANCED': {'pairs': 7, 'scans': 20, 'min_conf': 70},
    'ELITE': {'pairs': 99, 'scans': 999, 'min_conf': 75},
    'INSTITUTIONAL': {'pairs': 99, 'scans': 9999, 'min_conf': 75}
}

# ===== DB FUNCTIONS =====
def load_all():
    global USER_DATA, USERS_DB, SETTINGS, CHANNEL_ID
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
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                SETTINGS = json.load(f)
                if SETTINGS.get('channel_id'):
                    CHANNEL_ID = SETTINGS['channel_id']
        print("3. DB LOADED", flush=True)
    except Exception as e:
        print(f"LOAD ERROR: {e}", flush=True)

def save_all():
    try:
        with DATA_LOCK:
            with open(USER_DATA_FILE, 'w') as f:
                json.dump(USER_DATA, f, indent=2, default=str)
            with open(USERS_DB_FILE, 'w') as f:
                json.dump({str(k): {**v, 'expiry': v['expiry'].isoformat() if v.get('expiry') else None} for k, v in USERS_DB.items()}, f, indent=2)
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(SETTINGS, f, indent=2)
    except Exception as e:
        print(f"SAVE ERROR: {e}", flush=True)

def init_user(uid, username="Unknown"):
    uid_str = str(uid)
    with DATA_LOCK:
        if uid_str not in USER_DATA:
            USER_DATA[uid_str] = {'username': username, 'scans_today': 0, 'last_scan_date': str(datetime.now().date())}
        today = str(datetime.now().date())
        if USER_DATA[uid_str].get('last_scan_date')!= today:
            USER_DATA[uid_str]['scans_today'] = 0
            USER_DATA[uid_str]['last_scan_date'] = today
        save_all()

def get_tier(uid):
    try:
        uid = int(uid)
        if uid in USERS_DB:
            exp = USERS_DB[uid].get('expiry')
            if exp and isinstance(exp, datetime) and exp > datetime.now(timezone.utc):
                return USERS_DB[uid].get('tier', 'STARTER')
    except: pass
    return 'STARTER'

def has_access(uid):
    return get_tier(uid)!= 'STARTER'

def is_admin(uid):
    return int(uid) == ADMIN_ID

def get_channel_id():
    return SETTINGS.get('channel_id', CHANNEL_ID)

# ===== CHANNEL FUNCTIONS =====
def send_to_channel(text):
    channel = get_channel_id()
    if not channel:
        print("CHANNEL_ID not set, skipping channel post", flush=True)
        return False
    try:
        bot.send_message(channel, text, parse_mode='Markdown')
        print(f"POSTED TO CHANNEL {channel}", flush=True)
        return True
    except Exception as e:
        print(f"CHANNEL POST ERROR: {e}", flush=True)
        return False

# ===== SMC STRATEGY WITH TIMEFRAMES =====
def get_df(pair, interval='1m'):
    try:
        p = pair.replace('_OTC', '=X') if '_OTC' in pair else pair
        period_map = {'1m': '1d', '5m': '5d', '15m': '5d'}
        df = yf.Ticker(p).history(period=period_map.get(interval, '1d'), interval=interval, prepost=False)
        return df[['Open','High','Low','Close']].dropna() if not df.empty else None
    except Exception as e:
        print(f"DF ERROR {pair} {interval}: {e}", flush=True)
        return None

def analyze_smc(pair, timeframe='1m'):
    try:
        df = get_df(pair, interval=timeframe)
        if df is None or len(df) < 50:
            return None, f"No {timeframe} data"

        c, h, l = df['Close'].values, df['High'].values, df['Low'].values
        conf = 0
        direction = 0
        reasons = []

        lookback = 20 if timeframe == '1m' else 15 if timeframe == '5m' else 10
        if c[-1] > h[-lookback:-1].max():
            conf += 35
            direction = 1
            reasons.append("BOS Up")
        elif c[-1] < l[-lookback:-1].min():
            conf += 35
            direction = -1
            reasons.append("BOS Down")

        if direction == 1 and l[-1] < l[-10:-1].min():
            conf += 20
            reasons.append("Liq Sweep")
        elif direction == -1 and h[-1] > h[-10:-1].max():
            conf += 20
            reasons.append("Liq Sweep")

        mom_len = 10 if timeframe == '1m' else 6 if timeframe == '5m' else 4
        if len(c) > mom_len:
            mom = (c[-1] - c[-mom_len]) / c[-mom_len] * 100
            mom_threshold = 0.1 if timeframe == '1m' else 0.15 if timeframe == '5m' else 0.2
            if direction == 1 and mom > mom_threshold:
                conf += 15
                reasons.append("Bullish Mom")
            elif direction == -1 and mom < -mom_threshold:
                conf += 15
                reasons.append("Bearish Mom")

        if len(df) > 3:
            if direction == 1 and l[-1] > h[-3]:
                conf += 10
                reasons.append("Bull FVG")
            elif direction == -1 and h[-1] < l[-3]:
                conf += 10
                reasons.append("Bear FVG")

        if timeframe == '1m':
            htf_df = get_df(pair, interval='5m')
            if htf_df is not None and len(htf_df) > 20:
                htf_trend = 1 if htf_df['Close'].iloc[-1] > htf_df['Close'].iloc[-20] else -1
                if htf_trend == direction:
                    conf += 5
                    reasons.append("HTF Align")

        if conf < 65 or direction == 0:
            return None, f"No setup. Conf {conf}% on {timeframe}"

        eat = timezone(timedelta(hours=3))
        entry_mins = {'1m': 1, '5m': 5, '15m': 15}
        entry = (datetime.now(eat) + timedelta(minutes=entry_mins[timeframe])).replace(second=15, microsecond=0)

        return {
            'pair': pair,
            'direction': 'CALL' if direction == 1 else 'PUT',
            'confidence': min(conf, 95),
            'entry': entry,
            'reasons': reasons,
            'timeframe': timeframe
        }, None
    except Exception as e:
        print(f"ANALYSIS ERROR: {e}", flush=True)
        return None, f"Analysis error: {e}"

def format_signal(sig, for_channel=False):
    arrow = "⬆️⬆️⬆️ UP ⬆️⬆️⬆️" if sig['direction'] == 'CALL' else "⬇️⬇️⬇️ DOWN ⬇️⬇️⬇️"
    reasons_txt = " | ".join(sig['reasons'][:3])
    tf_txt = {'1m': 'S15', '5m': 'S30', '15m': 'M1'}[sig['timeframe']]

    header = "🔥 CHANNEL SIGNAL 🔥\n\n" if for_channel else ""
    footer = f"\n\n🤖 @YourBotUsername" if for_channel else ""

    return f"""{header}🟢 PROFIT POTENTIAL: {sig['confidence']}%

CURRENCY PAIR: {sig['pair'].replace('_OTC','').replace('=X','')}
TIME: {tf_txt}
TF: {sig['timeframe'].upper()}

{arrow}
{sig['entry'].strftime('%H:%M')} EAT

📊 {reasons_txt}{footer}
"""

# ===== USER HANDLERS =====
@bot.message_handler(commands=['start'])
def cmd_start(message):
    try:
        uid = message.from_user.id
        print(f"START FROM {uid}", flush=True)
        init_user(uid, message.from_user.username or message.from_user.first_name)
        tier = get_tier(uid)

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📊 Pocket Option OTC", callback_data="menu_po"),
            types.InlineKeyboardButton("💱 Forex Live", callback_data="menu_forex"),
            types.InlineKeyboardButton("🎁 Free Demo", callback_data="demo"),
            types.InlineKeyboardButton("💳 Upgrade", callback_data="upgrade")
        )
        if is_admin(uid):
            kb.add(types.InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin"))

        txt = f"👋 SMC ELITE BOT\n\nTier: {tier}\nID: `{uid}`\nTimeframes: M1 | M5 | M15\n\nM-Pesa: {MPESA_NUMBER}\nSupport: {SUPPORT_CONTACT}"
        bot.send_message(message.chat.id, txt, reply_markup=kb, parse_mode='Markdown')
        print(f"START SENT TO {uid}", flush=True)
    except Exception as e:
        print(f"START ERROR: {e}", flush=True)

@bot.message_handler(commands=['id'])
def cmd_id(message):
    try:
        uid = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        tier = get_tier(uid)
        exp = USERS_DB.get(uid, {}).get('expiry')
        exp_txt = exp.strftime('%Y-%m-%d %H:%M EAT') if exp else "No active sub"

        txt = f"🆔 YOUR ACCOUNT INFO\n\nUser ID: `{uid}`\nUsername: @{username}\nTier: {tier}\nExpiry: {exp_txt}\n\nCopy your User ID and send it with payment proof to {SUPPORT_CONTACT}"
        bot.reply_to(message, txt, parse_mode='Markdown')
        print(f"ID SENT TO {uid}", flush=True)
    except Exception as e:
        print(f"ID ERROR: {e}", flush=True)

@bot.message_handler(commands=['myinfo', 'me'])
def cmd_myinfo(message):
    cmd_id(message)

@bot.message_handler(commands=['demo'])
def cmd_demo(message):
    try:
        pair = random.choice(PAIRS_OTC[:3])
        eat = timezone(timedelta(hours=3))
        t = (datetime.now(eat) + timedelta(minutes=1)).strftime('%H:%M')
        txt = f"🎁 DEMO SIGNAL\n\nPAIR: {pair.replace('_OTC','')}\nTIME: S15\nTF: M1\n\n⬆️⬆️⬆️ UP ⬆️⬆️⬆️\n{t} EAT\n\nUpgrade for M5/M15 signals."
        bot.send_message(message.chat.id, txt)
        print(f"DEMO SENT", flush=True)
    except Exception as e:
        print(f"DEMO ERROR: {e}", flush=True)

# ===== ADMIN HANDLERS =====
@bot.message_handler(commands=['grant'])
def cmd_grant(message):
    if not is_admin(message.from_user.id):
        return
    try:
        parts = message.text.split()
        if len(parts)!= 4:
            bot.reply_to(message, "Usage: /grant <user_id> <TIER> <days>\n\nExample: /grant 8552719664 ELITE 30\n\nTiers: STARTER, ADVANCED, ELITE, INSTITUTIONAL")
            return
        uid = int(parts[1])
        tier = parts[2].upper()
        days = int(parts[3])
        if tier not in TIERS:
            bot.reply_to(message, f"Invalid tier. Use: {', '.join(TIERS.keys())}")
            return
        USERS_DB[uid] = {
            'tier': tier,
            'expiry': datetime.now(timezone.utc) + timedelta(days=days),
            'username': USER_DATA.get(str(uid), {}).get('username', 'Unknown')
        }
        save_all()
        bot.reply_to(message, f"✅ Granted {tier} to `{uid}` for {days} days", parse_mode='Markdown')
        try:
            bot.send_message(uid, f"🎉 Your {tier} access activated for {days} days!\n\nUse /start to get signals.")
        except: pass
        print(f"GRANTED {tier} TO {uid} FOR {days}D", flush=True)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['revoke'])
def cmd_revoke(message):
    if not is_admin(message.from_user.id):
        return
    try:
        parts = message.text.split()
        if len(parts)!= 2:
            bot.reply_to(message, "Usage: /revoke <user_id>\n\nExample: /revoke 8552719664")
            return
        uid = int(parts[1])
        if uid in USERS_DB:
            del USERS_DB[uid]
            save_all()
            bot.reply_to(message, f"✅ Revoked access for `{uid}`", parse_mode='Markdown')
            try:
                bot.send_message(uid, "❌ Your subscription has been revoked.")
            except: pass
        else:
            bot.reply_to(message, "User not found in database")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['users'])
def cmd_users(message):
    if not is_admin(message.from_user.id):
        return
    try:
        txt = "👥 ACTIVE USERS:\n\n"
        count = 0
        for uid, data in USERS_DB.items():
            exp = data.get('expiry')
            if exp and exp > datetime.now(timezone.utc):
                days_left = (exp - datetime.now(timezone.utc)).days
                username = data.get('username', 'Unknown')
                txt += f"`{uid}` - {data.get('tier')} - {days_left}d - @{username}\n"
                count += 1
        if count == 0:
            txt += "No active subscribers"
        else:
            txt += f"\nTotal: {count} active"
        bot.reply_to(message, txt, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if not is_admin(message.from_user.id):
        return
    total = len(USER_DATA)
    active = sum(1 for u in USERS_DB.values() if u.get('expiry') and u['expiry'] > datetime.now(timezone.utc))
    scans = sum(u.get('scans_today', 0) for u in USER_DATA.values())
    channel = get_channel_id() or 'Not Set'
    txt = f"📊 BOT STATS\n\nTotal Users: {total}\nActive Subs: {active}\nScans Today: {scans}\nChannel: `{channel}`"
    bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['channel'])
def cmd_channel(message):
    if not is_admin(message.from_user.id):
        return
    try:
        parts = message.text.split()
        current = get_channel_id() or 'Not Set'
        if len(parts)!= 2:
            bot.reply_to(message, f"Current Channel: `{current}`\n\nUsage: /channel <channel_id>\nExample: /channel -1001234567890", parse_mode='Markdown')
            return
        new_channel = parts[1]
        SETTINGS['channel_id'] = new_channel
        save_all()
        bot.reply_to(message, f"✅ Channel set to `{new_channel}`", parse_mode='Markdown')
        send_to_channel("🔔 SMC ELITE BOT connected to this channel.\n\nSignals with 75%+ confidence will be posted here automatically.")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['post'])
def cmd_post(message):
    if not is_admin(message.from_user.id):
        return
    try:
        pair = random.choice(PAIRS_OTC[:3])
        sig, _ = analyze_smc(pair, '1m')
        if sig:
            txt = format_signal(sig, for_channel=True)
            if send_to_channel(txt):
                bot.reply_to(message, "✅ Posted to channel")
            else:
                bot.reply_to(message, "❌ Failed. Check CHANNEL_ID and bot admin status")
        else:
            bot.reply_to(message, "❌ No signal generated to post")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

# ===== CALLBACK HANDLER =====
@bot.callback_query_handler(func=lambda call: True)
def callback_all(call):
    try:
        uid = call.from_user.id
        data = call.data
        print(f"CALLBACK {data} FROM {uid}", flush=True)

        if data == "demo":
            cmd_demo(call.message)
            bot.answer_callback_query(call.id)

        elif data == "upgrade":
            txt = f"💳 UPGRADE TIERS\n\n1️⃣ Run /id to get your User ID\n\n🥉 ADVANCED: KES 2,000/month\n20 scans/day, 7 pairs\n\n🥇 ELITE: KES 5,000/month\nUnlimited scans, all pairs\n\nM-Pesa: {MPESA_NUMBER}\n\nSend User ID + payment proof to {SUPPORT_CONTACT}"
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, txt)

        elif data == "admin":
            if not is_admin(uid):
                bot.answer_callback_query(call.id, "❌ Admin only", show_alert=True)
                return
            txt = f"⚙️ ADMIN PANEL\n\n/grant <id> <TIER> <days> - Give access\n/revoke <id> - Remove access\n/users - List active users\n/stats - Bot stats\n/channel <id> - Set channel\n/post - Test post to channel\n\nExample: /grant 8552719664 ELITE 30"
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, txt)

        elif data in ["menu_po", "menu_forex"]:
            if not has_access(uid):
                bot.answer_callback_query(call.id, "❌ Subscribe first. /demo for free signal", show_alert=True)
                return
            market = "po" if data == "menu_po" else "fx"
            kb = types.InlineKeyboardMarkup(row_width=3)
            kb.add(
                types.InlineKeyboardButton("M1", callback_data=f"tf_{market}_1m"),
                types.InlineKeyboardButton("M5", callback_data=f"tf_{market}_5m"),
                types.InlineKeyboardButton("M15", callback_data=f"tf_{market}_15m")
            )
            market_name = "Pocket Option OTC" if market == "po" else "Forex"
            bot.edit_message_text(f"📊 {market_name}\n\nSelect timeframe:", call.message.chat.id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif data.startswith("tf_"):
            parts = data.split("_")
            market = parts[1]
            tf = parts[2]
            pairs = PAIRS_OTC if market == "po" else PAIRS_FOREX
            kb = types.InlineKeyboardMarkup(row_width=3)
            btns = [types.InlineKeyboardButton(p.replace('_OTC','').replace('=X',''), callback_data=f"scan_{p}_{tf}") for p in pairs[:6]]
            kb.add(*btns)
            kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data=f"menu_{market}"))
            bot.edit_message_text(f"📊 Select pair for {tf.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif data.startswith("scan_"):
            parts = data.split("_")
            pair = "_".join(parts[1:-1]) if len(parts) > 2 else parts[1]
            tf = parts[-1]
            bot.answer_callback_query(call.id, f"Analyzing {pair} {tf}...")
            sig, err = analyze_smc(pair, tf)
            if sig:
                txt = format_signal(sig)
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("🔄 New Scan", callback_data=f"tf_{'po' if '_OTC' in pair else 'fx'}_{tf}"))
                bot.edit_message_text(txt, call.message.chat.id, call.message.message_id, reply_markup=kb)
                # Auto-post to channel if signal confidence >= 75%
                if sig['confidence'] >= 75:
                    channel_txt = format_signal(sig, for_channel=True)
                    send_to_channel(channel_txt)
            else:
                bot.edit_message_text(f"❌ {err}\n\nTry another pair/timeframe.", call.message.chat.id, call.message.message_id)

    except Exception as e:
        print(f"CALLBACK ERROR: {e}", flush=True)

print("4. Handlers registered", flush=True)

# ===== STARTUP =====
if __name__ == "__main__":
    print("=== STARTING BOT ===", flush=True)
    load_all()
    bot.delete_webhook(drop_pending_updates=True)
    print("5. POLLING STARTED - BOT IS LIVE", flush=True)
    bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
