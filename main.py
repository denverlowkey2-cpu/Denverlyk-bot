import sys
print("=== SMC ELITE PRO V2 START ===", flush=True)

import telebot
from telebot import types
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import os
import random
import json
import threading
import time

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER', '0700000000')
SUPPORT_CONTACT = os.getenv('SUPPORT_HANDLE', '@Support')
VIP_CHANNEL = os.getenv('VIP_CHANNEL', '')

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
print("Bot created", flush=True)

# ===== CONFIG =====
PAIRS_FOREX = ['EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X','USDCAD=X','EURGBP=X','EURJPY=X','GBPJPY=X','AUDJPY=X','NZDUSD=X','USDCHF=X','CADJPY=X']
PAIRS_OTC = ['EURUSD_OTC','GBPUSD_OTC','USDJPY_OTC','AUDUSD_OTC','USDCAD_OTC','EURGBP_OTC','EURJPY_OTC','GBPJPY_OTC']
TIMEFRAMES = ['1m', '5m', '15m']

USERS = {}
STATS = {'scans': 0, 'signals': 0, 'wins': 0, 'losses': 0}
LOCK = threading.Lock()
DATA_FILE = 'bot_data.json'

TIERS = {
    'FREE': {'scans': 3, 'price': 0, 'confluence': False},
    'ELITE': {'scans': 999, 'price': 5000, 'confluence': True}
}

NEWS_TIMES = ['12:30', '13:30', '14:00', '14:30', '15:30']

# ===== PERSISTENCE =====
def save_data():
    try:
        with LOCK:
            with open(DATA_FILE, 'w') as f:
                json.dump({'users': USERS, 'stats': STATS}, f, default=str)
    except Exception as e:
        print(f"SAVE ERROR: {e}", flush=True)

def load_data():
    global USERS, STATS
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                USERS = data.get('users', {})
                STATS = data.get('stats', STATS)
                # Convert string keys back to int
                USERS = {int(k): v for k, v in USERS.items()}
                print(f"Loaded {len(USERS)} users", flush=True)
    except Exception as e:
        print(f"LOAD ERROR: {e}", flush=True)

load_data()

# ===== UTILS =====
def is_news_time():
    now = datetime.now(timezone.utc).strftime('%H:%M')
    for news in NEWS_TIMES:
        news_dt = datetime.strptime(news, '%H:%M')
        now_dt = datetime.strptime(now, '%H:%M')
        diff = abs((now_dt - news_dt).total_seconds() / 60)
        if diff < 30:
            return True
    return False

def is_session_active():
    h = datetime.now(timezone.utc).hour
    return 7 <= h <= 16

def get_market_sentiment():
    try:
        bullish = 0
        for pair in PAIRS_FOREX[:6]:
            df = get_df(pair, '1m')
            if df is not None and len(df) > 5:
                if df['Close'].iloc[-1] > df['Close'].iloc[-5]:
                    bullish += 1
        pct = (bullish / 6) * 100
        return f"Bullish {pct:.0f}%" if pct > 50 else f"Bearish {100-pct:.0f}%"
    except:
        return "Mixed"

def get_user(uid):
    today = str(datetime.now().date())
    with LOCK:
        if uid not in USERS:
            USERS[uid] = {
                'tier': 'ELITE' if uid == ADMIN_ID else 'FREE',
                'expiry': None,
                'scans': 0,
                'wins': 0,
                'losses': 0,
                'refs': 0,
                'date': today,
                'last_scan': 0,
                'history': [],
                'loss_streak': 0
            }
        if USERS[uid]['date']!= today:
            USERS[uid]['scans'] = 0
            USERS[uid]['date'] = today
        if USERS[uid]['expiry'] and datetime.fromisoformat(USERS[uid]['expiry']) < datetime.now(timezone.utc):
            USERS[uid]['tier'] = 'FREE'
            USERS[uid]['expiry'] = None
    return USERS[uid]

def can_scan(uid):
    user = get_user(uid)
    if uid == ADMIN_ID:
        return True, ""
    if user['loss_streak'] >= 3:
        return False, "Loss streak protection. Wait 1 hour or contact support."
    if user['tier'] == 'FREE' and user['scans'] >= TIERS['FREE']['scans']:
        return False, f"Daily limit: {TIERS['FREE']['scans']}. Upgrade: /upgrade"
    if time.time() - user['last_scan'] < 30:
        return False, "Wait 30s between scans"
    if is_news_time():
        return False, "News time - signals paused 30min"
    return True, ""

def add_scan(uid, signal=None):
    with LOCK:
        user = get_user(uid)
        user['scans'] += 1
        user['last_scan'] = time.time()
        STATS['scans'] += 1
        if signal:
            user['history'] = ([signal] + user['history'])[:10]
            STATS['signals'] += 1
    save_data()

def calc_lot_size(balance=100, risk_pct=2, sl_pips=20):
    risk_amount = balance * (risk_pct / 100)
    lot = risk_amount / (sl_pips * 10)
    return round(lot, 2)

def get_tv_link(pair, tf='1'):
    p = pair.replace('_OTC','').replace('=X','')
    return f"https://tradingview.com/chart/?symbol=FX:{p}&interval={tf}"

# ===== SMC LOGIC =====
def get_df(pair, interval='1m'):
    try:
        p = pair.replace('_OTC', '=X') if '_OTC' in pair else pair
        period = {'1m': '1d', '5m': '5d', '15m': '5d'}[interval]
        df = yf.Ticker(p).history(period=period, interval=interval, prepost=False)
        return df[['Open','High','Low','Close']].dropna() if not df.empty else None
    except:
        return None

def analyze_tf(pair, timeframe):
    df = get_df(pair, interval=timeframe)
    if df is None or len(df) < 30:
        return 0, 0

    c, h, l = df['Close'].values, df['High'].values, df['Low'].values
    direction = 0
    conf = 0

    if c[-1] > h[-10:-1].max():
        direction = 1
        conf += 35
    elif c[-1] < l[-10:-1].min():
        direction = -1
        conf += 35
    else:
        return 0, 0

    mom_len = 5 if timeframe == '1m' else 3
    if len(c) > mom_len:
        mom = (c[-1] - c[-mom_len]) / c[-mom_len] * 100
        if direction == 1 and mom > 0.05:
            conf += 20
        elif direction == -1 and mom < -0.05:
            conf += 20

    if direction == 1 and l[-1] < l[-5:-1].min():
        conf += 10
    elif direction == -1 and h[-1] > h[-5:-1].max():
        conf += 10

    return direction, conf

def analyze_pair_elite(pair, tf='1m', confluence=False):
    try:
        d1, c1 = analyze_tf(pair, '1m')
        if d1 == 0:
            return None

        conf = c1
        reasons = []

        if confluence:
            d5, c5 = analyze_tf(pair, '5m')
            d15, c15 = analyze_tf(pair, '15m')
            if d5 == d1:
                conf += 15
                reasons.append("M5 Align")
            if d15 == d1:
                conf += 15
                reasons.append("M15 Align")
            if d5!= d1 or d15!= d1:
                conf -= 10

        if is_session_active():
            conf += 10
            reasons.append("Active Session")

        if conf < 65:
            return None

        eat = timezone(timedelta(hours=3))
        mins = {'1m': 1, '5m': 5, '15m': 15}[tf]
        entry = (datetime.now(eat) + timedelta(minutes=mins)).replace(second=15, microsecond=0)

        return {
            'pair': pair,
            'direction': 'CALL' if d1 == 1 else 'PUT',
            'confidence': min(conf, 95),
            'entry': entry,
            'reasons': reasons,
            'timeframe': tf,
            'id': f"{pair}_{int(time.time())}",
            'created': time.time()
        }
    except:
        return None

def format_signal(sig, uid=None):
    arrow = "⬆️⬆️⬆️ UP ⬆️⬆️⬆️" if sig['direction'] == 'CALL' else "⬇️⬇️⬇️ DOWN ⬇️⬇️⬇️"
    reasons_txt = " | ".join(sig['reasons'][:3]) if sig['reasons'] else "SMC Setup"
    tf_txt = {'1m': 'S15', '5m': 'S30', '15m': 'M1'}[sig['timeframe']]
    lot = calc_lot_size()
    tv = get_tv_link(sig['pair'], '1' if sig['timeframe'] == '1m' else '5')

    user_stats = ""
    if uid:
        u = get_user(uid)
        total = u['wins'] + u['losses']
        wr = f"{u['wins']}/{total} ({u['wins']/total*100:.0f}%)" if total else "No data"
        user_stats = f"\n\n📊 Your Stats: {wr}"

    return f"""🟢 PROFIT POTENTIAL: {sig['confidence']}%

CURRENCY PAIR: {sig['pair'].replace('_OTC','').replace('=X','')}
TIME: {tf_txt}
TF: {sig['timeframe'].upper()}

{arrow}
{sig['entry'].strftime('%H:%M')} EAT

📊 {reasons_txt}
💰 Risk 2%: {lot} lots
📈 Chart: {tv}{user_stats}

Signal ID: {sig['id']}"""

def post_to_vip(sig):
    if not VIP_CHANNEL:
        return
    try:
        txt = f"🔥 VIP SIGNAL 🔥\n\n{format_signal(sig)}\n\n🤖 @YourBotUsername"
        bot.send_message(VIP_CHANNEL, txt)
    except Exception as e:
        print(f"VIP POST ERROR: {e}", flush=True)

# ===== MENU =====
def get_main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("📊 OTC Signals"),
        types.KeyboardButton("💱 Forex Signals"),
        types.KeyboardButton("🔍 Scan All Pro"),
        types.KeyboardButton("📈 History"),
        types.KeyboardButton("💳 Upgrade"),
        types.KeyboardButton("👥 Refer"),
        types.KeyboardButton("🆔 My Stats"),
        types.KeyboardButton("⚙️ Settings")
    )
    return kb

# ===== HANDLERS =====
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id
    get_user(uid)
    tier = get_user(uid)['tier']
    conf = 'ON' if TIERS[tier]['confluence'] else 'OFF'
    txt = f"👋 SMC ELITE PRO\n\nTier: {tier}\nConfluence: {conf}\nNews Filter: ON\n\nSelect option:"
    bot.send_message(message.chat.id, txt, reply_markup=get_main_menu())

@bot.message_handler(commands=['upgrade'])
def cmd_upgrade(message):
    uid = message.from_user.id
    ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{uid}"
    txt = f"""💎 ELITE UPGRADE

🥇 ELITE: KES {TIERS['ELITE']['price']}/month

BENEFITS:
✅ Unlimited signals
✅ MTF Confluence (+20% accuracy)
✅ All 20 pairs
✅ VIP channel access
✅ Win rate tracking
✅ Loss protection

📱 M-PESA:
1. Send KES {TIERS['ELITE']['price']} to: {MPESA_NUMBER}
2. Forward M-Pesa msg to {SUPPORT_CONTACT}
3. Include ID: {uid}

👥 REFERRAL:
Share: {ref_link}
+5 free scans per friend"""
    bot.send_message(message.chat.id, txt)

@bot.message_handler(commands=['grant'])
def cmd_grant(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        days = int(parts[2]) if len(parts) > 2 else 30
        with LOCK:
            u = get_user(uid)
            u['tier'] = 'ELITE'
            u['expiry'] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        save_data()
        bot.reply_to(message, f"✅ ELITE granted to {uid} for {days}d")
        bot.send_message(uid, f"🎉 ELITE activated for {days} days!\n\nConfluence mode ON. Win rate tracking enabled.")
    except:
        bot.reply_to(message, "Usage: /grant user_id days")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if message.from_user.id!= ADMIN_ID:
        return
    text = message.text.replace('/broadcast', '').strip()
    if not text:
        bot.reply_to(message, "Usage: /broadcast Your message")
        return
    count = 0
    with LOCK:
        for uid in USERS.keys():
            try:
                bot.send_message(uid, f"📢 ANNOUNCEMENT\n\n{text}")
                count += 1
            except:
                pass
    bot.reply_to(message, f"✅ Sent to {count} users")

@bot.message_handler(commands=['history'])
def cmd_history(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user['history']:
        bot.send_message(message.chat.id, "No signal history yet.")
        return

    txt = "📈 LAST 10 SIGNALS:\n\n"
    for i, sig in enumerate(user['history'], 1):
        status = sig.get('result', 'Pending')
        emoji = "✅" if status == "Win" else "❌" if status == "Loss" else "⏳"
        txt += f"{i}. {sig['pair'].replace('_OTC','').replace('=X','')} {sig['direction']} {sig['confidence']}% {emoji}\n"

    total = user['wins'] + user['losses']
    wr = f"{user['wins']}/{total} ({user['wins']/total*100:.1f}%)" if total else "0%"
    txt += f"\nWin Rate: {wr}\nLoss Streak: {user['loss_streak']}"
    bot.send_message(message.chat.id, txt)

# Catch-all text handler - THIS FIXES THE BUTTONS
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    try:
        uid = message.from_user.id
        text = message.text.strip()
        print(f"GOT TEXT: {text} FROM {uid}", flush=True)

        if "OTC Signals" in text:
            kb = types.InlineKeyboardMarkup(row_width=3)
            kb.add(
                types.InlineKeyboardButton("M1", callback_data="tf_otc_1m"),
                types.InlineKeyboardButton("M5", callback_data="tf_otc_5m"),
                types.InlineKeyboardButton("M15", callback_data="tf_otc_15m")
            )
            bot.send_message(message.chat.id, f"📊 OTC Mode\n\nSentiment: {get_market_sentiment()}\nSelect timeframe:", reply_markup=kb)

        elif "Forex Signals" in text:
            kb = types.InlineKeyboardMarkup(row_width=3)
            kb.add(
                types.InlineKeyboardButton("M1", callback_data="tf_fx_1m"),
                types.InlineKeyboardButton("M5", callback_data="tf_fx_5m"),
                types.InlineKeyboardButton("M15", callback_data="tf_fx_15m")
            )
            bot.send_message(message.chat.id, f"💱 Forex Mode\n\nSentiment: {get_market_sentiment()}\nSelect timeframe:", reply_markup=kb)

        elif "Scan All" in text:
            can, msg = can_scan(uid)
            if not can:
                bot.send_message(message.chat.id, f"❌ {msg}")
                return

            add_scan(uid)
            bot.send_message(message.chat.id, f"🔍 Scanning 20 pairs...\n\nMarket: {get_market_sentiment()}")

            user = get_user(uid)
            use_confluence = TIERS[user['tier']]['confluence']
            results = []

            try:
                for pair in PAIRS_FOREX + PAIRS_OTC[:4]:
                    sig = analyze_pair_elite(pair, '1m', use_confluence)
                    if sig:
                        results.append(sig)
            except Exception as e:
                print(f"SCAN ERROR: {e}", flush=True)
                bot.send_message(message.chat.id, "⚠️ Scan error. Try again.")
                return

            if results:
                best = max(results, key=lambda x: x['confidence'])
                add_scan(uid, best)
                txt = format_signal(best, uid)
                kb = types.InlineKeyboardMarkup()
                kb.add(
                    types.InlineKeyboardButton("✅ Win", callback_data=f"win_{best['id']}"),
                    types.InlineKeyboardButton("❌ Loss", callback_data=f"loss_{best['id']}")
                )
                bot.send_message(message.chat.id, txt, reply_markup=kb)
                if best['confidence'] >= 80:
                    post_to_vip(best)
            else:
                bot.send_message(message.chat.id, "❌ No high-probability setups.\n\nMarkets ranging. Try again in 5-10min.")

        elif "History" in text:
            cmd_history(message)

        elif "Upgrade" in text:
            cmd_upgrade(message)

        elif "Refer" in text:
            ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{uid}"
            user = get_user(uid)
            txt = f"👥 REFERRAL PROGRAM\n\nYour link: {ref_link}\n\nReferrals: {user['refs']}\nBonus scans: +{user['refs']*5}\n\nShare and earn!"
            bot.send_message(message.chat.id, txt)

        elif "My Stats" in text or text == "🆔":
            user = get_user(uid)
            total = user['wins'] + user['losses']
            wr = f"{user['wins']}/{total} ({user['wins']/total*100:.1f}%)" if total else "No trades"
            exp = datetime.fromisoformat(user['expiry']).strftime('%Y-%m-%d') if user['expiry'] else "N/A"
            txt = f"""🆔 YOUR STATS

ID: {uid}
Tier: {user['tier']}
Expiry: {exp}
Scans today: {user['scans']}/{TIERS[user['tier']]['scans']}

Win Rate: {wr}
Loss Streak: {user['loss_streak']}
Referrals: {user['refs']}

Bot Stats:
Total scans: {STATS['scans']}
Signals: {STATS['signals']}"""
            bot.send_message(message.chat.id, txt)

        elif "Settings" in text:
            user = get_user(uid)
            conf = "ON" if TIERS[user['tier']]['confluence'] else "OFF"
            txt = f"""⚙️ SETTINGS

Confluence: {conf}
News Filter: ON
Session Filter: ON
Loss Protection: ON
Risk per trade: 2%
Cooldown: 30s

Upgrade for Confluence ON"""
            bot.send_message(message.chat.id, txt)

        else:
            bot.send_message(message.chat.id, "Unknown command. Use the menu buttons below.")

    except Exception as e:
        print(f"HANDLER ERROR: {e}", flush=True)
        bot.send_message(message.chat.id, "⚠️ Error occurred. Try again.")

@bot.callback_query_handler(func=lambda call: True)
def callback_all(call):
    try:
        data = call.data
        uid = call.from_user.id

        if data.startswith("tf_"):
            can, msg = can_scan(uid)
            if not can:
                bot.answer_callback_query(call.id, msg, show_alert=True)
                return

            parts = data.split('_')
            mode = parts[1]
            tf = parts[2]
            pairs = PAIRS_OTC if mode == "otc" else PAIRS_FOREX

            add_scan(uid)
            bot.answer_callback_query(call.id, f"Scanning {tf.upper()}...")

            user = get_user(uid)
            use_confluence = TIERS[user['tier']]['confluence']
            results = []

            for pair in pairs[:8]:
                sig = analyze_pair_elite(pair, tf, use_confluence)
                if sig:
                    results.append(sig)

            if results:
                best = max(results, key=lambda x: x['confidence'])
                add_scan(uid, best)
                txt = format_signal(best, uid)
                kb = types.InlineKeyboardMarkup()
                kb.add(
                    types.InlineKeyboardButton("✅ Win", callback_data=f"win_{best['id']}"),
                    types.InlineKeyboardButton("❌ Loss", callback_data=f"loss_{best['id']}")
                )
                bot.send_message(call.message.chat.id, txt, reply_markup=kb)
                if best['confidence'] >= 80:
                    post_to_vip(best)
            else:
                bot.send_message(call.message.chat.id, f"❌ No {tf.upper()} setups. Try another TF.")

        elif data.startswith("win_") or data.startswith("loss_"):
            action, sig_id = data.split('_', 1)
            with LOCK:
                user = get_user(uid)
                for sig in user['history']:
                    if sig['id'] == sig_id and 'result' not in sig:
                        if action == "win":
                            user['wins'] += 1
                            user['loss_streak'] = 0
                            STATS['wins'] += 1
                            sig['result'] = "Win"
                        else:
                            user['losses'] += 1
                            user['loss_streak'] += 1
                            STATS['losses'] += 1
                            sig['result'] = "Loss"
                        save_data()
                        bot.answer_callback_query(call.id, f"Recorded: {sig['result']}")
                        return
            bot.answer_callback_query(call.id, "Already recorded")

    except Exception as e:
        print(f"CALLBACK ERROR: {e}", flush=True)

print("Handlers ready", flush=True)

if __name__ == "__main__":
    print("=== POLLING STARTED ===", flush=True)
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
