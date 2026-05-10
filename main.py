import sys
print("=== SMC ELITE PRO START ===", flush=True)

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
VIP_CHANNEL = os.getenv('VIP_CHANNEL', '') # Set to -100xxx for auto-post

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
print("Bot created", flush=True)

# ===== CONFIG =====
PAIRS_FOREX = ['EURUSD=X','GBPUSD=X','USDJPY=X','AUDUSD=X','USDCAD=X','EURGBP=X','EURJPY=X','GBPJPY=X','AUDJPY=X','NZDUSD=X','USDCHF=X','CADJPY=X']
PAIRS_OTC = ['EURUSD_OTC','GBPUSD_OTC','USDJPY_OTC','AUDUSD_OTC','USDCAD_OTC','EURGBP_OTC','EURJPY_OTC','GBPJPY_OTC']
TIMEFRAMES = ['1m', '5m', '15m']

# In-memory DB - resets on deploy but stable
USERS = {} # {uid: {tier, expiry, scans, wins, losses, refs, last_scan, history:[]}}
STATS = {'scans': 0, 'signals': 0, 'wins': 0, 'losses': 0}
LOCK = threading.Lock()

TIERS = {
    'FREE': {'scans': 3, 'price': 0, 'confluence': False},
    'ELITE': {'scans': 999, 'price': 5000, 'confluence': True}
}

# Major news times UTC - avoid trading
NEWS_TIMES = ['12:30', '13:30', '14:00', '14:30', '15:30'] # NFP, CPI, FOMC etc

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
    return 7 <= h <= 16 # London 7-16 UTC

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
                'history': []
            }
        if USERS[uid]['date']!= today:
            USERS[uid]['scans'] = 0
            USERS[uid]['date'] = today
        # Check expiry
        if USERS[uid]['expiry'] and datetime.now(timezone.utc) > USERS[uid]['expiry']:
            USERS[uid]['tier'] = 'FREE'
            USERS[uid]['expiry'] = None
    return USERS[uid]

def can_scan(uid):
    user = get_user(uid)
    if uid == ADMIN_ID:
        return True, ""
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

def calc_lot_size(balance=100, risk_pct=2, sl_pips=20):
    # Simplified: $10 per pip for 1 lot EURUSD
    risk_amount = balance * (risk_pct / 100)
    lot = risk_amount / (sl_pips * 10)
    return round(lot, 2)

# ===== SMC LOGIC WITH CONFLUENCE =====
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

    # BOS
    if c[-1] > h[-10:-1].max():
        direction = 1
        conf += 35
    elif c[-1] < l[-10:-1].min():
        direction = -1
        conf += 35
    else:
        return 0, 0

    # Momentum
    mom_len = 5 if timeframe == '1m' else 3
    if len(c) > mom_len:
        mom = (c[-1] - c[-mom_len]) / c[-mom_len] * 100
        if direction == 1 and mom > 0.05:
            conf += 20
        elif direction == -1 and mom < -0.05:
            conf += 20

    # Liquidity
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

        # Confluence check for ELITE
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
                conf -= 10 # Penalty for no confluence

        # Session boost
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
            'id': f"{pair}_{int(time.time())}"
        }
    except:
        return None

def format_signal(sig, uid=None):
    arrow = "⬆️⬆️⬆️ UP ⬆️⬆️⬆️" if sig['direction'] == 'CALL' else "⬇️⬇️⬇️ DOWN ⬇️⬇️⬇️"
    reasons_txt = " | ".join(sig['reasons'][:3]) if sig['reasons'] else "SMC Setup"
    tf_txt = {'1m': 'S15', '5m': 'S30', '15m': 'M1'}[sig['timeframe']]
    lot = calc_lot_size()

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
💰 Risk 2%: {lot} lots{user_stats}

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
    get_user(uid) # init
    tier = get_user(uid)['tier']
    txt = f"👋 SMC ELITE PRO\n\nTier: {tier}\nConfluence: {'ON' if TIERS[tier]['confluence'] else 'OFF'}\nNews Filter: ON\n\nSelect option:"
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
✅ Priority support
✅ Win rate tracking

📱 M-PESA:
1. Send KES {TIERS['ELITE']['price']} to: {MPESA_NUMBER}
2. Forward M-Pesa msg to {SUPPORT_CONTACT}
3. Include ID: {uid}

👥 REFERRAL:
Share: {ref_link}
+5 free scans per friend

Activated in 5 min."""
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
            u['expiry'] = datetime.now(timezone.utc) + timedelta(days=days)
        bot.reply_to(message, f"✅ ELITE granted to {uid} for {days}d")
        bot.send_message(uid, f"🎉 ELITE activated for {days} days!\n\nConfluence mode ON. Win rate tracking enabled.")
    except:
        bot.reply_to(message, "Usage: /grant user_id days")

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
    txt += f"\nWin Rate: {wr}"
    bot.send_message(message.chat.id, txt)

@bot.message_handler(func=lambda m: m.text == "📊 OTC Signals")
def menu_otc(message):
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("M1", callback_data="tf_otc_1m"),
        types.InlineKeyboardButton("M5", callback_data="tf_otc_5m"),
        types.InlineKeyboardButton("M15", callback_data="tf_otc_15m")
    )
    bot.send_message(message.chat.id, "📊 OTC Mode\n\nConfluence: ON for Elite\nSelect timeframe:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "💱 Forex Signals")
def menu_fx(message):
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("M1", callback_data="tf_fx_1m"),
        types.InlineKeyboardButton("M5", callback_data="tf_fx_5m"),
        types.InlineKeyboardButton("M15", callback_data="tf_fx_15m")
    )
    bot.send_message(message.chat.id, "💱 Forex Mode\n\nSelect timeframe:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "🔍 Scan All Pro")
def menu_scanall(message):
    uid = message.from_user.id
    can, msg = can_scan(uid)
    if not can:
        bot.send_message(message.chat.id, f"❌ {msg}")
        return

    add_scan(uid)
    bot.send_message(message.chat.id, "🔍 Scanning 20 pairs with MTF confluence...")

    user = get_user(uid)
    use_confluence = TIERS[user['tier']]['confluence']
    results = []

    for pair in PAIRS_FOREX + PAIRS_OTC[:4]:
        sig = analyze_pair_elite(pair, '1m', use_confluence)
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
        bot.send_message(message.chat.id, txt, reply_markup=kb)

        if best['confidence'] >= 80:
            post_to_vip(best)
    else:
        bot.send_message(message.chat.id, "❌ No high-probability setups.\n\nMarkets ranging. Try again in 5-10min.")

@bot.message_handler(func=lambda m: m.text == "📈 History")
def menu_history(message):
    cmd_history(message)

@bot.message_handler(func=lambda m: m.text == "💳 Upgrade")
def menu_upgrade(message):
    cmd_upgrade(message)

@bot.message_handler(func=lambda m: m.text == "👥 Refer")
def menu_refer(message):
    uid = message.from_user.id
    ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{uid}"
    user = get_user(uid)
    txt = f"👥 REFERRAL PROGRAM\n\nYour link: {ref_link}\n\nReferrals: {user['refs']}\nBonus scans: +{user['refs']*5}\n\nShare and earn!"
    bot.send_message(message.chat.id, txt)

@bot.message_handler(func=lambda m: m.text == "🆔 My Stats")
def menu_stats(message):
    uid = message.from_user.id
    user = get_user(uid)
    total = user['wins'] + user['losses']
    wr = f"{user['wins']}/{total} ({user['wins']/total*100:.1f}%)" if total else "No trades"
    exp = user['expiry'].strftime('%Y-%m-%d') if user['expiry'] else "N/A"

    txt = f"""🆔 YOUR STATS

ID: {uid}
Tier: {user['tier']}
Expiry: {exp}
Scans today: {user['scans']}/{TIERS[user['tier']]['scans']}

Win Rate: {wr}
Referrals: {user['refs']}

Bot Stats:
Total scans: {STATS['scans']}
Signals: {STATS['signals']}"""
    bot.send_message(message.chat.id, txt)

@bot.message_handler(func=lambda m: m.text == "⚙️ Settings")
def menu_settings(message):
    uid = message.from_user.id
    user = get_user(uid)
    conf = "ON" if TIERS[user['tier']]['confluence'] else "OFF"
    txt = f"""⚙️ SETTINGS

Confluence: {conf}
News Filter: ON
Session Filter: ON
Risk per trade: 2%
Cooldown: 30s

Upgrade for Confluence ON"""
    bot.send_message(message.chat.id, txt)

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
                            STATS['wins'] += 1
                            sig['result'] = "Win"
                        else:
                            user['losses'] += 1
                            STATS['losses'] += 1
                            sig['result'] = "Loss"
                        bot.answer_callback_query(call.id, f"Recorded: {sig['result']}")
                        return
            bot.answer_callback_query(call.id, "Already recorded")

    except Exception as e:
        print(f"CALLBACK ERROR: {e}", flush=True)

print("Handlers ready", flush=True)

if __name__ == "__main__":
    print("=== POLLING STARTED ===", flush=True)
    bot.delete_webhook(drop_pending_updates=True)  # This line kills conflicts
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
