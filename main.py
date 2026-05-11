import sys
print("=== DENVER SMC ELITE V3.3 FINAL START ===", flush=True)

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
MPESA_NUMBER = os.getenv('MPESA_NUMBER')
SUPPORT_CONTACT = os.getenv('SUPPORT_HANDLE')
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
    'FREE': {'scans': 3, 'confluence': False},
    'WEEKLY': {'scans': 999, 'price': 1000, 'days': 7, 'confluence': True},
    'MONTHLY': {'scans': 999, 'price': 5500, 'days': 30, 'confluence': True}
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
                USERS = {int(k): v for k, v in data.get('users', {}).items()}
                STATS = data.get('stats', STATS)
                print(f"Loaded {len(USERS)} users", flush=True)
    except Exception as e:
        print(f"LOAD ERROR: {e}", flush=True)

load_data()

# ===== UTILS =====
def is_news_time():
    try:
        now = datetime.now(timezone.utc).strftime('%H:%M')
        for news in NEWS_TIMES:
            news_dt = datetime.strptime(news, '%H:%M')
            now_dt = datetime.strptime(now, '%H:%M')
            diff = abs((now_dt - news_dt).total_seconds() / 60)
            if diff < 30:
                return True
        return False
    except:
        return False

def is_session_active():
    try:
        h = datetime.now(timezone.utc).hour
        return 7 <= h <= 16
    except:
        return True

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
                'tier': 'MONTHLY' if uid == ADMIN_ID else 'FREE',
                'expiry': None,
                'scans': 0,
                'wins': 0,
                'losses': 0,
                'refs': 0,
                'date': today,
                'last_scan': 0,
                'history': [],
                'loss_streak': 0,
                'loss_streak_time': 0,
                'banned': False
            }
        if USERS[uid]['date']!= today:
            USERS[uid]['scans'] = 0
            USERS[uid]['date'] = today

        # AUTO RESET LOSS STREAK after 1 hour
        if USERS[uid]['loss_streak'] >= 3:
            if time.time() - USERS[uid].get('loss_streak_time', 0) > 3600:
                USERS[uid]['loss_streak'] = 0
                USERS[uid]['loss_streak_time'] = 0
                print(f"AUTO RESET loss streak for {uid}", flush=True)

        # Check expiry
        if USERS[uid]['expiry']:
            try:
                exp_dt = datetime.fromisoformat(USERS[uid]['expiry'])
                if datetime.now(timezone.utc) > exp_dt:
                    USERS[uid]['tier'] = 'FREE'
                    USERS[uid]['expiry'] = None
                    USERS[uid]['loss_streak'] = 0
            except:
                USERS[uid]['tier'] = 'FREE'
                USERS[uid]['expiry'] = None
    return USERS[uid]

def can_scan(uid):
    user = get_user(uid)
    if uid == ADMIN_ID:
        return True, ""
    if user['banned']:
        return False, "Account suspended. Contact support."
    if user['loss_streak'] >= 3:
        wait_min = int(60 - (time.time() - user.get('loss_streak_time', 0)) / 60)
        return False, f"Loss protection active. Auto-reset in {wait_min}min. Or upgrade to reset instantly."
    if user['tier'] == 'FREE' and user['scans'] >= TIERS['FREE']['scans']:
        return False, f"Daily limit: {TIERS['FREE']['scans']}. Upgrade: /upgrade"
    if time.time() - user['last_scan'] < 30:
        return False, "Wait 30s between scans"
    if is_news_time():
        return False, "News time - signals paused 30min for safety"
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

def get_tv_link(pair, tf='1'):
    try:
        p = pair.replace('_OTC','').replace('=X','')
        return f"https://tradingview.com/chart/?symbol=FX:{p}&interval={tf}"
    except:
        return ""

# ===== SMC LOGIC =====
def get_df(pair, interval='1m'):
    try:
        p = pair.replace('_OTC', '=X') if '_OTC' in pair else pair
        period = {'1m': '1d', '5m': '5d', '15m': '5d'}[interval]
        df = yf.Ticker(p).history(period=period, interval=interval, prepost=False)
        return df[['Open','High','Low','Close']].dropna() if not df.empty else None
    except Exception as e:
        print(f"DF ERROR {pair}: {e}", flush=True)
        return None

def analyze_tf(pair, timeframe):
    try:
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
    except:
        return 0, 0

def analyze_pair_elite(pair, tf='1m', confluence=False):
    try:
        d1, c1 = analyze_tf(pair, '1m')
        if d1 == 0:
            return None

        conf = c1
        reasons = ["BOS"]

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
    except Exception as e:
        print(f"ANALYZE ERROR: {e}", flush=True)
        return None

def format_signal(sig, uid=None):
    try:
        arrow = "⬆️⬆️⬆️ UP ⬆️⬆️⬆️" if sig['direction'] == 'CALL' else "⬇️⬇️ DOWN ⬇️⬇️⬇️"
        reasons_txt = " | ".join(sig['reasons'][:3])
        tf_txt = {'1m': 'S15', '5m': 'S30', '15m': 'M1'}[sig['timeframe']]
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
📈 Chart: {tv}{user_stats}

Expires in 5min | ID: {sig['id'][-6:]}"""
    except:
        return "Signal format error"

def post_to_vip(sig):
    if not VIP_CHANNEL:
        return
    try:
        txt = f"🔥 VIP SIGNAL {sig['confidence']}% 🔥\n\n{format_signal(sig)}\n\n🤖 @Denverlyksignalpro"
        bot.send_message(VIP_CHANNEL, txt)
    except Exception as e:
        print(f"VIP POST ERROR: {e}", flush=True)

# ===== MENU =====
def get_main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🔍 Scan All Pro"),
        types.KeyboardButton("📈 History"),
        types.KeyboardButton("📊 OTC Signals"),
        types.KeyboardButton("💱 Forex Signals"),
        types.KeyboardButton("💳 Upgrade"),
        types.KeyboardButton("👥 Refer"),
        types.KeyboardButton("🆔 My Stats"),
        types.KeyboardButton("⚙️ Settings")
    )
    return kb

# ===== HANDLERS =====
@bot.message_handler(commands=['start'])
def cmd_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        conf_status = "ON" if TIERS[user['tier']]['confluence'] else "OFF"
        exp = ""
        if user['expiry']:
            try:
                exp_dt = datetime.fromisoformat(user['expiry'])
                days_left = (exp_dt - datetime.now(timezone.utc)).days
                exp = f"\nExpires: {days_left} days"
            except:
                exp = ""

        txt = f"👋 DENVER SMC ELITE\n\nTier: {user['tier']}{exp}\nConfluence: {conf_status}\nNews Filter: ON\n\nSelect option:"
        bot.send_message(message.chat.id, txt, reply_markup=get_main_menu())
        print(f"START OK {uid}", flush=True)
    except Exception as e:
        print(f"START ERROR: {e}", flush=True)
        bot.send_message(message.chat.id, "Welcome! Use menu below.")

@bot.message_handler(commands=['upgrade'])
def cmd_upgrade(message):
    try:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("📅 WEEKLY - KES 1,000", callback_data="pay_weekly"),
            types.InlineKeyboardButton("📅 MONTHLY - KES 5,500", callback_data="pay_monthly")
        )
        txt = f"""💎 CHOOSE YOUR PLAN

🥇 WEEKLY ELITE: KES 1,000
- 7 days unlimited signals
- MTF Confluence ON
- Auto-resets loss protection

🥇 MONTHLY ELITE: KES 5,500
- 30 days unlimited signals
- Save KES 1,500
- All features unlocked

Select plan below:"""
        bot.send_message(message.chat.id, txt, reply_markup=kb)
    except Exception as e:
        print(f"UPGRADE ERROR: {e}", flush=True)

@bot.message_handler(commands=['grant'])
def cmd_grant(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        parts = message.text.split()
        uid = int(parts[1])
        tier = parts[2].upper()
        if tier not in ['WEEKLY', 'MONTHLY']:
            bot.reply_to(message, "Usage: /grant user_id WEEKLY or MONTHLY")
            return
        days = TIERS[tire]['days'] # FIXED
        with LOCK:
            u = get_user(uid)
            u['tier'] = tier
            u['expiry'] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            u['loss_streak'] = 0
            u['loss_streak_time'] = 0
        save_data()
        bot.reply_to(message, f"✅ {tier} granted to {uid} for {days}d")
        bot.send_message(uid, f"🎉 {tier} ELITE activated for {days} days!\n\nLoss protection reset. Confluence ON.")
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)[:100]}")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
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
    except:
        bot.reply_to(message, "Broadcast error")

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    try:
        uid = message.from_user.id
        text = message.text.strip()
        print(f"MSG: {text} FROM {uid}", flush=True)

        if "Scan All Pro" in text:
            can, msg = can_scan(uid)
            if not can:
                bot.send_message(message.chat.id, f"❌ {msg}")
                return

            add_scan(uid)
            bot.send_message(message.chat.id, f"🔍 Scanning 20 pairs...\n\nMarket: {get_market_sentiment()}")

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
            return

        if "History" in text:
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
            txt += f"\nWin Rate: {wr}\nLoss Streak: {user['loss_streak']}/3"
            bot.send_message(message.chat.id, txt)
            return

        if "My Stats" in text or "ID" in text:
            user = get_user(uid)
            total = user['wins'] + user['losses']
            wr = f"{user['wins']}/{total} ({user['wins']/total*100:.1f}%)" if total else "No trades"
            exp = "Lifetime"
            if user['expiry']:
                try:
                    exp_dt = datetime.fromisoformat(user['expiry'])
                    days = (exp_dt - datetime.now(timezone.utc)).days
                    exp = f"{days} days left"
                except:
                    exp = "Error"
            txt = f"""🆔 YOUR STATS

ID: {uid}
Tier: {user['tier']}
Expiry: {exp}
Scans today: {user['scans']}/{TIERS[user['tier']]['scans']}

Win Rate: {wr}
Loss Streak: {user['loss_streak']}/3
Referrals: {user['refs']}

Bot Stats:
Total scans: {STATS['scans']}
Signals: {STATS['signals']}"""
            bot.send_message(message.chat.id, txt)
            return

        if "Upgrade" in text:
            cmd_upgrade(message)
            return

        if "Refer" in text:
            ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{uid}"
            user = get_user(uid)
            txt = f"""👥 REFERRAL PROGRAM

Your link: {ref_link}

Referrals: {user['refs']}
Bonus: +7 days ELITE per referral

Share and earn free membership!"""
            bot.send_message(message.chat.id, txt)
            return

        if "Settings" in text:
            user = get_user(uid)
            conf = "ON" if TIERS[user['tier']]['confluence'] else "OFF"
            txt = f"""⚙️ SETTINGS

Confluence: {conf}
News Filter: ON
Session Filter: ON
Loss Protection: Auto-reset 1hr
Risk per trade: 2%
Cooldown: 30s

Upgrade for Confluence ON"""
            bot.send_message(message.chat.id, txt)
            return

        if "OTC" in text or "Forex" in text:
            bot.send_message(message.chat.id, "Use 'Scan All Pro' for best signals. Direct pair selection coming soon.")
            return

        bot.send_message(message.chat.id, "Use the menu buttons below.")

    except Exception as e:
        print(f"HANDLER ERROR: {e}", flush=True)
        bot.send_message(message.chat.id, f"⚠️ Error: {str(e)[:100]}")

@bot.callback_query_handler(func=lambda call: True)
def callback_all(call):
    try:
        data = call.data
        uid = call.from_user.id

        if data == "pay_weekly" or data == "pay_monthly":
            tier = "WEEKLY" if "weekly" in data else "MONTHLY"
            price = TIERS[tire]['price'] # FIXED
            days = TIERS[tire]['days'] # FIXED
            txt = f"""💰 {tier} PAYMENT

Amount: KES {price}
Duration: {days} days

📱 M-PESA STEPS:
1. Go to M-Pesa → Lipa na M-Pesa
2. PayBill: 000000 (or Buy Goods)
3. Number: {MPESA_NUMBER}
4. Amount: {price}
5. Send M-Pesa message to {SUPPORT_CONTACT}
6. Include: {tier} {uid}

Activated in 5 minutes!"""
            bot.send_message(call.message.chat.id, txt)
            bot.answer_callback_query(call.id)
            return

        if data.startswith("win_") or data.startswith("loss_"):
            action, sig_id = data.split('_', 1)
            with LOCK:
                user = get_user(uid)
                for sig in user['history']:
                    if sig['id'] == sig_id and 'result' not in sig:
                        if action == "win":
                            user['wins'] += 1
                            user['loss_streak'] = 0
                            user['loss_streak_time'] = 0
                            STATS['wins'] += 1
                            sig['result'] = "Win"
                        else:
                            user['losses'] += 1
                            user['loss_streak'] += 1
                            if user['loss_streak'] == 1:
                                user['loss_streak_time'] = time.time()
                            STATS['losses'] += 1
                            sig['result'] = "Loss"
                            if user['loss_streak'] >= 3:
                                bot.send_message(uid, "⚠️ Loss protection activated. Auto-reset in 1 hour. Upgrade to reset instantly.")
                        save_data()
                        bot.answer_callback_query(call.id, f"Recorded: {sig['result']}")
                        return
            bot.answer_callback_query(call.id, "Already recorded")

    except Exception as e:
        print(f"CALLBACK ERROR: {e}", flush=True)
        bot.answer_callback_query(call.id, "Error")

print("Handlers ready", flush=True)

if __name__ == "__main__":
    print("=== POLLING STARTED ===", flush=True)
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
