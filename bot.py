# force restart - May 02 2026
import sys
print("=== CONTAINER STARTED ===", flush=True)

import os
print("=== IMPORTING ===", flush=True)
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
import sqlite3
import asyncio
import mplfinance as mpf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
from gtts import gTTS
import io

print("=== ALL IMPORTS DONE ===", flush=True)

# ===== CONFIG FROM RAILWAY VARIABLES =====
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
TD_KEY = os.getenv('TD_KEY')
SUPPORT_HANDLE = os.getenv('SUPPORT_HANDLE')
MPESA_NUMBER = os.getenv('MPESA_NUMBER')

print(f"=== TOKEN LENGTH: {len(BOT_TOKEN)} ===", flush=True)
if not BOT_TOKEN:
    print("=== ERROR: BOT_TOKEN IS EMPTY ===", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

try:
    me = bot.get_me()
    print(f"=== BOT USERNAME: @{me.username} ===", flush=True)
except Exception as e:
    print(f"=== BOT.GET_ME FAILED: {e} ===", flush=True)
    sys.exit(1)

# ===== DATABASE SETUP =====
DB_PATH = 'bot_data.db'
SIGNAL_FILE = 'signal_history.json'
USER_PNL_FILE = 'user_pnl.json'
NEWS_CACHE_FILE = 'news_cache.json'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  tier TEXT,
                  expiry_notified INTEGER DEFAULT 0)''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN expiry TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN expiry_notified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def load_users():
    USERS_DATA = {}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, tier, expiry, expiry_notified FROM users")
    rows = c.fetchall()
    for row in rows:
        user_id, tier, expiry_str, notified = row
        expiry = datetime.fromisoformat(expiry_str) if expiry_str else None
        USERS_DATA[user_id] = {
            'tier': tier,
            'expiry': expiry,
            'expiry_notified': bool(notified) if notified is not None else False
        }
    conn.close()
    print(f"=== LOADED {len(USERS_DATA)} USERS FROM DB ===", flush=True)
    return USERS_DATA

def save_user(user_id, tier, expiry, expiry_notified=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    expiry_str = expiry.isoformat() if expiry else None
    c.execute("""INSERT OR REPLACE INTO users
                 (user_id, tier, expiry, expiry_notified)
                 VALUES (?,?,?,?)""",
              (user_id, tier, expiry_str, int(expiry_notified)))
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE user_id =?", (user_id,))
    conn.commit()
    conn.close()

init_db()
USERS_DATA = load_users()

# ===== SIGNAL HISTORY & PNL =====
def load_signals():
    try:
        with open(SIGNAL_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"signals": [], "stats": {"wins": 0, "losses": 0}, "streak": 0}

def save_signals(data):
    with open(SIGNAL_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_user_pnl():
    try:
        with open(USER_PNL_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_user_pnl(data):
    with open(USER_PNL_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# ===== NEWS FILTER =====
def get_forex_news():
    try:
        with open(NEWS_CACHE_FILE, 'r') as f:
            cache = json.load(f)
            if time.time() - cache['time'] < 3600:
                return cache['events']
    except:
        pass

    feed = feedparser.parse('https://www.forexfactory.com/ffcal_week_this.xml')
    events = []
    high_impact = ['Non-Farm', 'NFP', 'CPI', 'FOMC', 'Interest Rate', 'GDP', 'Unemployment']

    for entry in feed.entries:
        if any(impact in entry.title for impact in high_impact):
            try:
                event_time = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z')
                events.append({
                    'time': event_time.isoformat(),
                    'title': entry.title,
                    'impact': 'High'
                })
            except:
                continue

    with open(NEWS_CACHE_FILE, 'w') as f:
        json.dump({'time': time.time(), 'events': events}, f)
    return events

def is_news_time():
    events = get_forex_news()
    now = datetime.now(timezone.utc)
    for event in events:
        event_time = datetime.fromisoformat(event['time'])
        diff = abs((now - event_time).total_seconds() / 60)
        if diff <= 30:
            return True, event['title']
    return False, None

# ===== CHART GENERATION =====
def generate_chart(pair, df, confluence, signal_id):
    try:
        df_plot = df.tail(50).copy()
        df_plot.index = pd.to_datetime(df_plot['datetime'])
        df_plot = df_plot[['open', 'high', 'low', 'close']]

        df_plot['EMA20'] = ta.trend.ema_indicator(df_plot['close'], 20)
        df_plot['EMA50'] = ta.trend.ema_indicator(df_plot['close'], 50)

        apds = [
            mpf.make_addplot(df_plot['EMA20'], color='cyan', width=1),
            mpf.make_addplot(df_plot['EMA50'], color='magenta', width=1)
        ]

        if confluence.get('fvg_zone'):
            fvg = confluence['fvg_zone']
            apds.append(mpf.make_addplot([fvg['high']]*len(df_plot), color='lime', alpha=0.3))
            apds.append(mpf.make_addplot([fvg['low']]*len(df_plot), color='lime', alpha=0.3))

        fig, _ = mpf.plot(
            df_plot, type='candle', style='charles',
            title=f'{pair} - A+ Setup {confluence["score"]}/100',
            ylabel='Price', volume=False, addplot=apds,
            returnfig=True, figsize=(12, 8)
        )

        chart_path = f'/tmp/{signal_id}.png'
        fig.savefig(chart_path, dpi=100, bbox_inches='tight')
        plt.close(fig)
        return chart_path
    except Exception as e:
        print(f"Chart error: {e}", flush=True)
        return None

# ===== POCKET OPTION OTC PAIRS - 18 TOTAL =====
PAIRS = [
    'EURUSD_OTC', 'GBPUSD_OTC', 'AUDUSD_OTC', 'USDJPY_OTC', 'USDCAD_OTC', 'NZDUSD_OTC',
    'EURJPY_OTC', 'GBPJPY_OTC', 'AUDJPY_OTC', 'EURAUD_OTC', 'EURGBP_OTC', 'EURCAD_OTC',
    'EURCHF_OTC', 'GBPAUD_OTC', 'GBPCHF_OTC', 'AUDCAD_OTC', 'XAUUSD_OTC', 'AUDNZD_OTC'
]

# ===== DATA STORAGE + CACHE =====
user_data = {}
DATA_FILE = 'user_data.json'
price_cache = {}
CACHE_DURATION = 60

# ===== MESSAGES =====
START_MSG = f"""
🔥 *DENVERLYK SIGNALS - POCKET OPTION ELITE*

Choose your access level:

💰 *NORMAL - 1000 KSH / 7 Days*
✅ 10 B+ signals per day
✅ 60%+ confidence setups
✅ Last 5 signals + settings

💎 *VIP - 2000 KSH / 7 Days*
✅ Unlimited signals
✅ A+ 75%+ setups only
✅ Live charts with FVG/OB marked
✅ Auto killzone alerts - 60s early
✅ 18 pairs scanned
✅ News filter protection

👑 *ELITE - 5000 KSH / 7 Days*
✅ Everything in VIP +
✅ Voice alerts for A+ signals
✅ Personal PnL tracker
✅ Backtest any pair 30 days
✅ Priority support
✅ Win streak bonuses

*Pay via M-Pesa to:* *{MPESA_NUMBER}*
Use your @username as reference.

Pick your plan below 👇
"""

NORMAL_MSG = f"""
💰 *NORMAL ACCESS - 1000 KSH / 7 Days*

*You get:*
✅ 10 signals per day
✅ B+ 60%+ confidence setups
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
✅ Unlimited signals
✅ Auto alerts - 60s early
✅ Killzone auto scan - 10AM & 3PM EAT
✅ A+ 75%+ confidence only
✅ 1M/5M expiry on Pocket Option
✅ 18 pairs monitored
✅ Live chart screenshots
✅ News filter protection

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
            'scans_today': 0, 'is_vip': False, 'is_normal': False, 'is_elite': False,
            'vip_expiry': None, 'normal_expiry': None, 'elite_expiry': None,
            'username': username, 'last_scan_date': str(datetime.now().date()),
            'signal_history': [], 'pnl': 0, 'wins': 0, 'losses': 0,
            'settings': {'killzone_pings': True, 'min_confidence': 60, 'quiet_hours': False, 'voice_alerts': True}
        }
        save_data()

def sync_vip_status(user_id):
    uid = str(user_id)
    if user_id in USERS_DATA:
        tier = USERS_DATA[user_id].get('tier')
        expiry = USERS_DATA[user_id].get('expiry')
        if expiry and expiry > datetime.now(timezone.utc):
            if tier == 'VIP':
                user_data[uid]['is_vip'] = True
                user_data[uid]['vip_expiry'] = expiry.isoformat()
            elif tier == 'ELITE':
                user_data[uid]['is_elite'] = True
                user_data[uid]['is_vip'] = True
                user_data[uid]['elite_expiry'] = expiry.isoformat()
        else:
            user_data[uid]['is_vip'] = False
            user_data[uid]['is_elite'] = False
            user_data[uid]['vip_expiry'] = None
            user_data[uid]['elite_expiry'] = None
    else:
        user_data[uid]['is_vip'] = False
        user_data[uid]['is_elite'] = False

def check_subscription_expiry(user_id):
    uid = str(user_id)
    if uid not in user_data:
        return
    sync_vip_status(int(user_id))
    if user_data[uid]['is_normal'] and user_data[uid]['normal_expiry']:
        expiry = datetime.fromisoformat(user_data[uid]['normal_expiry'])
        if datetime.now() > expiry:
            user_data[uid]['is_normal'] = False
            user_data[uid]['normal_expiry'] = None
            save_data()

def has_access(user_id):
    if int(user_id) == ADMIN_ID:
        return True
    check_subscription_expiry(user_id)
    return user_data[user_id]['is_vip'] or user_data[user_id]['is_elite'] or user_data[user_id]['is_normal']

def is_quiet_hours(user_id):
    if not user_data[user_id]['settings']['quiet_hours']: return False
    hour = datetime.now(timezone.utc).hour
    return hour >= 19 or hour < 4

def get_daily_limit(user_id):
    uid = str(user_id)
    if int(user_id) == ADMIN_ID or user_data[uid]['is_elite']:
        return 999
    if user_data[uid]['is_vip']:
        return 999
    if user_data[uid]['is_normal']:
        return 10
    return 0

def can_scan_today(user_id):
    uid = str(user_id)
    today = str(datetime.now().date())
    if user_data[uid]['last_scan_date']!= today:
        user_data[uid]['scans_today'] = 0
        user_data[uid]['last_scan_date'] = today
        save_data()
    limit = get_daily_limit(user_id)
    scans = user_data[uid]['scans_today']
    return scans < limit, scans, limit

def get_td_data(pair, interval='1min', outputsize=200, force_fresh=False):
    global price_cache
    now = time.time()
    cache_key = f"{pair}_{interval}"
    if not force_fresh and cache_key in price_cache:
        if now - price_cache[cache_key]['time'] < CACHE_DURATION:
            return price_cache[cache_key]['data']
    api_pair = pair.replace('_OTC', '')
    url = f"https://api.twelvedata.com/time_series?symbol={api_pair}&interval={interval}&outputsize={outputsize}&apikey={TD_KEY}"
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
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'volume' in df:
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    return df

# ===== STRATEGY FUNCTIONS =====
def check_killzone():
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    return (7 <= hour < 10) or (12 <= hour < 15)

def check_htf_trend(df_1h):
    if len(df_1h) < 50: return 0
    ema20 = ta.trend.ema_indicator(df_1h['close'], 20).iloc[-1]
    ema50 = ta.trend.ema_indicator(df_1h['close'], 50).iloc[-1]
    return 1 if ema20 > ema50 else -1

def detect_bos_choch(df):
    if len(df) < 20: return 0, None
    recent_high = df['high'].iloc[-20:-1].max()
    recent_low = df['low'].iloc[-20:-1].min()
    last_close = df['close'].iloc[-1]
    if last_close > recent_high: return 1, 'bullish_bos'
    if last_close < recent_low: return -1, 'bearish_bos'
    return 0, None

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

def analyze_pocket_pair(pair, is_vip, user_min_conf):
    news_active, news_title = is_news_time()
    if news_active:
        print(f"=== NEWS BLOCK: {news_title} ===", flush=True)
        return None

    data_1m = get_td_data(pair, '1min', 200, force_fresh=False)
    data_5m = get_td_data(pair, '5min', 200, force_fresh=False)
    data_1h = get_td_data(pair, '1h', 200, force_fresh=False)

    df_1m = df_from_td(data_1m)
    df_5m = df_from_td(data_5m)
    df_1h = df_from_td(data_1h)

    if df_1m is None or len(df_1m) < 50: return None

    confidence = 0
    direction = 0
    confluence = {'score': 0, 'breakdown': [], 'fvg_zone': None}

    killzone = check_killzone()
    bos_dir, bos_type = detect_bos_choch(df_1m)
    fvg_dir, fvg_zone = detect_fvg(df_1m)
    ob_dir = detect_order_block(df_1m)
    htf_trend = check_htf_trend(df_1h) if df_1h is not None else 0

    rsi = ta.momentum.RSIIndicator(df_1m['close'], 14).rsi()
    rsi_div = 0
    if len(rsi) > 20:
        if df_1m['close'].iloc[-1] < df_1m['close'].iloc[-10] and rsi.iloc[-1] > rsi.iloc[-10]:
            rsi_div = 1
        elif df_1m['close'].iloc[-1] > df_1m['close'].iloc[-10] and rsi.iloc[-1] < rsi.iloc[-10]:
            rsi_div = -1

    if bos_dir!= 0:
        confidence += 20; direction = bos_dir
        confluence['breakdown'].append(f"✅ 1m {bos_type.replace('_', ' ').title()} +20")
    if fvg_dir == direction and fvg_dir!= 0:
        confidence += 20
        confluence['breakdown'].append(f"✅ 1m FVG Retest +20")
        confluence['fvg_zone'] = fvg_zone
    if ob_dir == direction and ob_dir!= 0:
        confidence += 20
        confluence['breakdown'].append(f"✅ Order Block +20")
    if htf_trend == direction and htf_trend!= 0:
        confidence += 20
        confluence['breakdown'].append(f"✅ 1H Trend Align +20")
    if killzone:
        confidence += 20
        confluence['breakdown'].append(f"✅ London/NY Killzone +20")
    if rsi_div == direction and rsi_div!= 0:
        confidence += 12
        confluence['breakdown'].append(f"✅ RSI Divergence +12")

    min_conf = 60 if not is_vip else 60
    if confidence < min_conf or direction == 0: return None

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
        'df_1m': df_1m
    }

def format_pocket_signal(signal, is_vip, is_elite=False):
    vip_tag = "👑 *ELITE A+ SIGNAL*" if is_elite else "💎 *VIP A+ SIGNAL*" if signal['grade'] == 'A+' and is_vip else "📊 *B+ SIGNAL*"
    early_tag = "\n⚡ *60s EARLY ALERT*" if is_vip else ""
    direction_arrow = "⬆️ CALL" if signal['direction'] == 'CALL' else "⬇️ PUT"

    confluence_text = "\n*Confluence Breakdown:*\n"
    for item in signal['confluence']['breakdown']:
        confluence_text += f"{item}\n"

    martingale = ""
    if is_elite and signal['grade'] == 'A+':
        next_time = (signal['entry_time'] + timedelta(minutes=5)).strftime('%H:%M:%S')
        martingale = f"\n\n🔄 *If Loss:* Next entry {next_time}, 2.2x size"

    return f"""
{vip_tag}{early_tag}

*Pair:* {signal['pair']}
*Direction:* {direction_arrow}
*Entry:* {signal['entry_time'].strftime('%H:%M:%S')} EAT sharp
*Expiry:* {signal['expiry']}

*Grade:* {signal['grade']} ({signal['confidence']}/100)
{confluence_text}
⚠️ Enter at exact second. Do not late enter.
Risk 1-2% max per trade.{martingale}

Not financial advice.
"""

def save_signal_to_history(user_id, signal):
    hist = user_data[user_id]['signal_history']
    hist.insert(0, {
        'direction': signal['direction'], 'pair': signal['pair'],
        'expiry': signal['expiry'], 'entry_time': signal['entry_time'].strftime('%H:%M'),
        'confidence': signal['confidence'], 'grade': signal['grade'],
        'timestamp': signal['timestamp']
    })
    user_data[user_id]['signal_history'] = hist[:5]
    save_data()

async def log_signal_sent(pair, direction, confidence, entry_time, df_1m, confluence):
    data = load_signals()
    signal_id = f"{pair}_{entry_time.strftime('%Y%m%d_%H%M%S')}"
    chart_path = generate_chart(pair, df_1m, confluence, signal_id)

    data["signals"].append({
        "id": signal_id, "pair": pair, "direction": direction,
        "confidence": confidence, "entry_time": entry_time.isoformat(),
        "result": "pending", "chart": chart_path, "confluence": confluence
    })
    save_signals(data)

    for uid_str in user_data:
        uid = int(uid_str)
        is_user_vip = user_data[uid_str]['is_vip'] or user_data[uid_str]['is_elite'] or uid == ADMIN_ID
        is_elite = user_data[uid_str]['is_elite']
        if is_user_vip and has_access(uid_str):
            try:
                if chart_path:
                    with open(chart_path, 'rb') as photo:
                        bot.send_photo(uid, photo, caption=f"📊 *{pair} A+ Setup*\n\nConfluence: {confidence}%\nEntry: {entry_time.strftime('%H:%M:%S')}", parse_mode='Markdown')

                if is_elite and user_data[uid_str]['settings']['voice_alerts']:
                    tts = gTTS(f"Elite signal. {direction} on {pair.replace('_OTC','')}. Enter at {entry_time.strftime('%H %M %S')}", lang='en')
                    voice_fp = io.BytesIO()
                    tts.write_to_fp(voice_fp)
                    voice_fp.seek(0)
                    bot.send_voice(uid, voice_fp)
            except Exception as e:
                print(f"Send error: {e}", flush=True)

    await asyncio.sleep(360)
    try:
        await bot.send_message(
            ADMIN_ID,
            text=f"📊 Result check: {pair} {direction} from {entry_time.strftime('%H:%M')}\n\nDid it win?\n/win_{signal_id}\n/loss_{signal_id}"
        )
    except Exception as e:
        print(f"Failed to send result DM: {e}", flush=True)

def auto_scan_pocket_vip():
    if not check_killzone():
        print("=== KILLZONE NOT ACTIVE - SKIP AUTO SCAN ===", flush=True)
        return

    news_active, news_title = is_news_time()
    if news_active:
        print(f"=== AUTO SCAN BLOCKED BY NEWS: {news_title} ===", flush=True)
        return

    print("=== RUNNING VIP AUTO SCAN ===", flush=True)
    signals_sent = 0
    data = load_signals()
    streak = data.get('streak', 0)

    for pair in PAIRS:
        signal = analyze_pocket_pair(pair, is_vip=True, user_min_conf=75)
        if signal and signal['confidence'] >= 75:
            if streak >= 3:
                for uid_str in user_data:
                    uid = int(uid_str)
                    if (user_data[uid_str]['is_vip'] or user_data[uid_str]['is_elite']) and has_access(uid_str):
                        try:
                            bot.send_message(uid, f"🔥 *{streak}-WIN STREAK ACTIVE*\n\nNext signal is HOT. Stay ready.", parse_mode='Markdown')
                        except:
                            pass

            asyncio.run(log_signal_sent(signal['pair'], signal['direction'], signal['confidence'],
                                      signal['entry_time'], signal['df_1m'], signal['confluence']))
            signals_sent += 1

    if signals_sent > 0:
        try:
            bot.send_message(ADMIN_ID, f"✅ Auto scan complete. Sent {signals_sent} A+ signals.", parse_mode='Markdown')
        except: pass
    print(f"=== AUTO SCAN DONE: {signals_sent} SIGNALS SENT ===", flush=True)

# ===== EXPIRY AUTO-DM =====
def check_expired_vips():
    print("=== RUNNING EXPIRY CHECK ===", flush=True)
    now = datetime.now(timezone.utc)
    expired_today = []
    for uid, data in list(USERS_DATA.items()):
        expiry = data.get('expiry')
        tier = data.get('tier')
        if tier in ['VIP', 'ELITE'] and expiry and expiry < now:
            hours_since_expiry = (now - expiry).total_seconds() / 3600
            if 0 < hours_since_expiry < 24 and not data.get('expiry_notified'):
                try:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("💎 Renew VIP - 2000 KSH/week", callback_data="choose_vip"))
                    markup.add(types.InlineKeyboardButton("👑 Renew Elite - 5000 KSH/week", callback_data="choose_elite"))
                    bot.send_message(
                        uid,
                        f"😢 *{tier} EXPIRED*\n\nYour {tier} access ended on `{expiry.strftime('%d %b %Y')}`\n\nRenew now to keep getting A+ auto alerts and unlimited signals.",
                        parse_mode='Markdown', reply_markup=markup
                    )
                    USERS_DATA[uid]['expiry_notified'] = True
                    save_user(uid, tier, expiry, True)
                    expired_today.append(uid)
                    print(f"=== SENT EXPIRY DM TO {uid} ===", flush=True)
                except Exception as e:
                    print(f"=== FAILED TO DM {uid}: {e} ===", flush=True)
    if expired_today:
        try:
            bot.send_message(ADMIN_ID, f"📧 Sent expiry DMs to `{len(expired_today)}` users", parse_mode='Markdown')
        except:
            pass

# ===== BOT COMMANDS ===== #
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    print(f"=== /START BY {user_id} ===", flush=True)
    init_user(str(user_id), message.from_user.username or message.from_user.first_name)

    if user_id == ADMIN_ID:
        print(f"=== ADMIN ACCESS FOR {user_id} ===", flush=True)
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn1 = types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal")
        btn2 = types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats")
        btn3 = types.InlineKeyboardButton("🕐 Last 5 Signals", callback_data="last_signals")
        btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
        btn5 = types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")
        btn6 = types.InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")
        markup.add(btn1, btn2, btn3, btn4, btn5, btn6)

        bot.send_message(
            message.chat.id,
            f"🔥 *Welcome Admin @Denverlyksignalpro* 🔧\n\nID: `{user_id}`\nAccess: Unlimited\nPairs: 18\n\nUse signals + manage users below:",
            parse_mode='Markdown',
            reply_markup=markup
        )
        return

    if user_id in USERS_DATA:
        user = USERS_DATA[user_id]
        expiry = user.get('expiry')
        if user.get('tier') in ['VIP', 'ELITE'] and expiry and datetime.now(timezone.utc) < expiry:
            print(f"=== {user.get('tier')} ACCESS GRANTED FOR {user_id} ===", flush=True)
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn1 = types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal")
            btn2 = types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats")
            btn3 = types.InlineKeyboardButton("🕐 Last 5 Signals", callback_data="last_signals")
            btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            btn5 = types.InlineKeyboardButton("📊 Leaderboard", callback_data="leaderboard")
            markup.add(btn1, btn2, btn3, btn4, btn5)
            expiry_str = expiry.strftime("%d %b %Y")
            tier = "👑 ELITE" if user.get('tier') == 'ELITE' else "💎 VIP"
            bot.send_message(message.chat.id, f"🔥 *Welcome back {tier} @{message.from_user.username}*\n\nExpires: {expiry_str}\nScans: Unlimited\nPairs: 18", parse_mode='Markdown', reply_markup=markup)
            return

    print(f"=== SHOWING PAYMENT PAGE TO {user_id} ===", flush=True)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💰 Normal - 1000 KSH/week", callback_data="choose_normal"))
    markup.add(types.InlineKeyboardButton("💎 VIP - 2000 KSH/week", callback_data="choose_vip"))
    markup.add(types.InlineKeyboardButton("👑 Elite - 5000 KSH/week", callback_data="choose_elite"))
    bot.send_message(message.chat.id, START_MSG, parse_mode='Markdown', reply_markup=markup)

# ===== ADMIN COMMANDS =====
@bot.message_handler(commands=['adduser'])
def cmd_adduser(message):
    user_id = message.from_user.id
    print(f"=== /ADDUSER HIT BY {user_id} ===", flush=True)
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "Usage: `/adduser USER_ID VIP`\nExample: `/adduser 8552719664 VIP`", parse_mode='Markdown')
            return
        target_id = int(args[1])
        tier = args[2].upper()
        expiry_date = datetime.now(timezone.utc) + timedelta(days=7)
        if tier not in ['VIP', 'NORMAL', 'ELITE']:
            bot.reply_to(message, "❌ Tier must be VIP, ELITE, or NORMAL")
            return
        USERS_DATA[target_id] = {'tier': tier, 'expiry': expiry_date, 'expiry_notified': False}
        save_user(target_id, tier, expiry_date, False)
        bot.reply_to(message, f"✅ Added `{target_id}` as {tier}\nExpires: `{expiry_date.strftime('%d %b %Y')}`", parse_mode='Markdown')
        print(f"=== SAVED: {target_id} ===", flush=True)
        try:
            bot.send_message(target_id, f"🎉 {tier} access activated!\n\nExpires: {expiry_date.strftime('%d %b %Y')}\n\nType /start to begin", parse_mode='Markdown')
        except:
            pass
    except ValueError:
        bot.reply_to(message, "❌ User ID must be a number")
    except Exception as e:
        print(f"=== ADDUSER ERROR: {e} ===", flush=True)
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['removeuser'])
def cmd_removeuser(message):
    user_id = message.from_user.id
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        args = message.text.split()
        if len(args)!= 2:
            bot.reply_to(message, "Usage: `/removeuser USER_ID`", parse_mode='Markdown')
            return
        target_id = int(args[1])
        if target_id in USERS_DATA:
            del USERS_DATA[target_id]
            delete_user(target_id)
            bot.reply_to(message, f"✅ Removed `{target_id}`", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ User `{target_id}` not found", parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, "❌ Invalid USER_ID. Must be a number")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['renewuser'])
def cmd_renewuser(message):
    user_id = message.from_user.id
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: `/renewuser USER_ID DAYS`\n\nExample: `/renewuser 123456789 7`\nDefault: 7 days", parse_mode='Markdown')
            return
        target_id = int(args[1])
        days = int(args[2]) if len(args) > 2 else 7
        if target_id not in USERS_DATA:
            bot.reply_to(message, f"❌ User `{target_id}` not found. Use `/adduser` first", parse_mode='Markdown')
            return
        current_expiry = USERS_DATA[target_id].get('expiry')
        now = datetime.now(timezone.utc)
        if current_expiry and current_expiry > now:
            new_expiry = current_expiry + timedelta(days=days)
        else:
            new_expiry = now + timedelta(days=days)
        tier = USERS_DATA[target_id]['tier']
        USERS_DATA[target_id]['expiry'] = new_expiry
        USERS_DATA[target_id]['expiry_notified'] = False
        save_user(target_id, tier, new_expiry, False)
        new_expiry_str = new_expiry.strftime("%d %b %Y %H:%M")
        bot.reply_to(message, f"✅ Renewed `{target_id}`\n\nNew expiry: `{new_expiry_str}`\nAdded: `{days} days`", parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, "❌ Invalid USER_ID or DAYS. Must be numbers")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['listusers'])
def cmd_listusers(message):
    user_id = message.from_user.id
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    if not USERS_DATA:
        bot.reply_to(message, "📂 *USER LIST*\n\nNo users in database yet.", parse_mode='Markdown')
        return
    now = datetime.now(timezone.utc)
    active_vips = []
    active_elites = []
    expired = []
    for uid, data in USERS_DATA.items():
        tier = data.get('tier', 'Unknown')
        expiry = data.get('expiry')
        if expiry:
            expiry_str = expiry.strftime("%d %b %Y")
            days_left = (expiry - now).days
            status = f"✅ {days_left}d left" if expiry > now else f"❌ Expired"
            line = f"`{uid}` | {tier} | {expiry_str} | {status}"
            if expiry > now:
                if tier == 'ELITE':
                    active_elites.append(line)
                else:
                    active_vips.append(line)
            else:
                expired.append(line)
        else:
            line = f"`{uid}` | {tier} | No expiry"
            active_vips.append(line)
    msg = f"📂 *USER LIST*\n\n*Active Elite: {len(active_elites)}*\n"
    msg += "\n".join(active_elites[:10])
    msg += f"\n\n*Active VIP: {len(active_vips)}*\n"
    msg += "\n".join(active_vips[:10])
    if len(active_vips) > 10:
        msg += f"\n...and {len(active_vips) - 10} more"
    if expired:
        msg += f"\n\n*Expired: {len(expired)}*\n"
        msg += "\n".join(expired[:5])
    msg += f"\n\n*Total in DB: {len(USERS_DATA)}*"
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['testautoping'])
def cmd_testautoping(message):
    user_id = message.from_user.id
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    bot.reply_to(message, "🚀 Triggering test auto ping...")
    auto_scan_pocket_vip()

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    user_id = message.from_user.id
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        text = message.text.replace('/broadcast', '').strip()
        if not text:
            bot.reply_to(message, "Usage: `/broadcast YOUR MESSAGE`", parse_mode='Markdown')
            return
        sent_count = 0
        failed_count = 0
        for uid, data in USERS_DATA.items():
            if data.get('tier') in ['VIP', 'ELITE']:
                try:
                    bot.send_message(uid, f"📢 *ANNOUNCEMENT*\n\n{text}", parse_mode='Markdown')
                    sent_count += 1
                    time.sleep(0.05)
                except Exception as e:
                    failed_count += 1
        bot.reply_to(message, f"✅ Broadcast sent\n\nDelivered: `{sent_count}`\nFailed: `{failed_count}`", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    user_id = message.from_user.id
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    now = datetime.now(timezone.utc)
    total_users = len(USERS_DATA)
    active_vip = 0
    active_elite = 0
    expired = 0
    revenue_week = 0
    expiring_3days = 0
    expiring_today = 0
    for uid, data in USERS_DATA.items():
        tier = data.get('tier')
        expiry = data.get('expiry')
        if expiry and expiry > now:
            if tier == 'VIP':
                active_vip += 1
                revenue_week += 2000
            elif tier == 'ELITE':
                active_elite += 1
                revenue_week += 5000
            days_left = (expiry - now).days
            if days_left <= 0:
                expiring_today += 1
            elif days_left <= 3:
                expiring_3days += 1
        elif expiry:
            expired += 1
    total_paid = active_vip + active_elite
    churn_rate = (expired / (total_paid + expired) * 100) if (total_paid + expired) > 0 else 0
    msg = f"""📊 *BOT STATISTICS*

*👥 USERS*
Total: `{total_users}`
Active VIP: `{active_vip}` 💎
Active Elite: `{active_elite}` 👑
Expired: `{expired}` ❌

*💰 REVENUE ESTIMATE*
This Week: `{revenue_week:,} KSH`
*VIP: 2000 | Elite: 5000*

*⚠️ CHURN ALERTS*
Expiring Today: `{expiring_today}`
Expiring in 3 Days: `{expiring_3days}`
Churn Rate: `{churn_rate:.1f}%`

*📈 GROWTH*
Paid Conversion: `{(total_paid/total_users*100) if total_users > 0 else 0:.1f}%`
Pairs Monitored: `18`
"""
    bot.reply_to(message, msg, parse_mode='Markdown')

# ===== WIN/LOSS TRACKING =====
@bot.message_handler(commands=['win', 'loss'])
def mark_result(message):
    if message.from_user.id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only")
        return
    parts = message.text.split('_', 1)
    if len(parts) < 2:
        bot.reply_to(message, "Invalid format")
        return
    result = parts[0][1:]
    signal_id = parts[1]

    data = load_signals()
    user_pnl = load_user_pnl()

    for s in data["signals"]:
        if s["id"] == signal_id and s["result"] == "pending":
            s["result"] = result
            if result == "win":
                data["stats"]["wins"] += 1
                data["streak"] = data.get("streak", 0) + 1
                for uid_str in user_data:
                    if user_data[uid_str]['is_vip'] or user_data[uid_str]['is_elite']:
                        user_pnl[uid_str] = user_pnl.get(uid_str, 0) + 100
                        user_data[uid_str]['wins'] += 1
            else:
                data["stats"]["losses"] += 1
                data["streak"] = 0
                for uid_str in user_data:
                    if user_data[uid_str]['is_vip'] or user_data[uid_str]['is_elite']:
                        user_pnl[uid_str] = user_pnl.get(uid_str, 0) - 100
                        user_data[uid_str]['losses'] += 1
                        if user_data[uid_str]['is_elite']:
                            try:
                                next_time = (datetime.now(timezone(timedelta(hours=3))) + timedelta(minutes=5)).strftime('%H:%M:%S')
                                bot.send_message(int(uid_str), f"⚠️ *Loss Logged*\n\nMartingale Entry: {next_time}\nSize: 2.2x\nPair: {s['pair']}", parse_mode='Markdown')
                            except:
                                pass

            save_signals(data)
            save_user_pnl(user_pnl)
            save_data()
            return bot.reply_to(message, f"✅ Logged {result.upper()} for {s['pair']}\nStreak: {data['streak']}")
    bot.reply_to(message, "❌ Already marked or not found")

@bot.message_handler(commands=['botstats'])
def show_bot_stats(message):
    if message.from_user.id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only")
        return
    data = load_signals()
    w, l = data["stats"]["wins"], data["stats"]["losses"]
    total = w + l
    if total == 0:
        return bot.reply_to(message, "📊 *Signal Stats*\n\nNo signals logged yet", parse_mode='Markdown')
    wr = round(w / total * 100, 1)

    week_ago = datetime.now() - timedelta(days=7)
    week_signals = [s for s in data["signals"]
                   if datetime.fromisoformat(s["entry_time"]) > week_ago
                   and s["result"] in ["win", "loss"]]
    week_wins = len([s for s in week_signals if s["result"] == "win"])
    week_total = len(week_signals)
    week_wr = round(week_wins / week_total * 100, 1) if week_total > 0 else 0

    last_5 = ""
    for s in data["signals"][-5:][::-1]:
        result_emoji = "✅" if s["result"] == "win" else "❌" if s["result"] == "loss" else "⏳"
        last_5 += f"{result_emoji} {s['pair']} {s['direction']} - {s['result'].upper()}\n"

    msg = f"""📊 *Signal Performance*

*All Time:* {w}W {l}L = {wr}%
*This Week:* {week_wins}W {week_total-week_wins}L = {week_wr}%
*Current Streak:* {data.get('streak', 0)} wins

*Last 5 Signals:*
{last_5 if last_5 else 'No signals yet'}
"""
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['mystats'])
def show_my_stats(message):
    uid = str(message.from_user.id)
    if uid not in user_data:
        return bot.reply_to(message, "❌ No data yet. Take some signals first!")

    u = user_data[uid]
    pnl = load_user_pnl().get(uid, 0)
    total = u['wins'] + u['losses']
    wr = round(u['wins'] / total * 100, 1) if total > 0 else 0

    bot.reply_to(message, f"""
📈 *Your Personal Stats*

*P&L:* {pnl:,} KSH
*Signals Taken:* {total}
*Wins:* {u['wins']} ✅
*Losses:* {u['losses']} ❌
*Win Rate:* {wr}%

Keep grinding! 💎
""", parse_mode='Markdown')

@bot.message_handler(commands=['leaderboard'])
def show_leaderboard(message):
    user_pnl = load_user_pnl()
    if not user_pnl:
        return bot.reply_to(message, "📊 *Leaderboard*\n\nNo data yet this week")

    week_ago = datetime.now() - timedelta(days=7)
    # Filter users with recent activity
    active_users = []
    for uid, pnl in user_pnl.items():
        if uid in user_data:
            active_users.append((uid, pnl, user_data[uid]['username']))

    top_5 = sorted(active_users, key=lambda x: x[1], reverse=True)[:5]

    msg = "🏆 *Weekly Leaderboard*\n\n"
    medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
    for i, (uid, pnl, username) in enumerate(top_5):
        msg += f"{medals[i]} @{username} - {pnl:,} KSH\n"

    msg += "\n_Update: Every Sunday_"
    bot.reply_to(message, msg, parse_mode='Markdown')

# ===== CALLBACK HANDLERS =====
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = str(call.from_user.id)
    uid = int(user_id)
    check_subscription_expiry(uid)
    init_user(user_id, call.from_user.username or call.from_user.first_name)

    if call.data == "choose_normal":
        bot.edit_message_text(NORMAL_MSG, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif call.data == "choose_vip":
        bot.edit_message_text(VIP_MSG, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif call.data == "choose_elite":
        elite_msg = f"""
👑 *ELITE UPGRADE - 5000 KSH / 7 Days*

*You get:*
✅ Everything in VIP +
✅ Voice alerts for A+ signals
✅ Personal PnL tracker
✅ Backtest any pair 30 days
✅ Priority support
✅ Win streak bonuses
✅ Martingale calculator

*Pay via M-Pesa:*
1. Send Money to *{MPESA_NUMBER}*
2. Amount: 5000 KSH
3. Reference: Your @username
4. Send screenshot here

Bot activates in 5-10 mins.
"""
        bot.edit_message_text(elite_msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif call.data == "get_myid":
        user_id = call.from_user.id
        username = call.from_user.username or call.from_user.first_name
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            f"🆔 *Your Telegram ID*\n\nUser: @{username}\nID: `{user_id}`\n\n*Next steps:*\n1. Copy your ID above\n2. Pay 1000 KSH for Normal OR 2000 KSH for VIP OR 5000 KSH for Elite to M-Pesa: `{MPESA_NUMBER}`\n3. Send ID + payment screenshot to {SUPPORT_HANDLE}\n\nYou'll be activated in 5-10min ✅",
            parse_mode='Markdown'
        )

    elif call.data == "get_signal":
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired. Renew to continue.")
            return

        allowed, scans, limit = can_scan_today(user_id)
        if not allowed:
            bot.answer_callback_query(call.id, f"Daily limit {limit} reached. Upgrade to VIP for unlimited.")
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP", callback_data="choose_vip"))
            markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu"))
            bot.edit_message_text(
                f"🚫 *Daily Limit Reached*\n\nYou've used {scans}/{limit} scans today.\n\nNormal: 10/day\nVIP: Unlimited + 60s early alerts",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup
            )
            return

        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [types.InlineKeyboardButton(pair.replace('_OTC',''), callback_data=f"scan_{pair}") for pair in PAIRS]
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_menu"))
        markup.add(*buttons)
        bot.edit_message_text(f"Select pair to scan:\n\n_Scans today: {scans}/{limit}_", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data == "my_stats":
        is_vip = user_data[user_id]['is_vip'] or uid == ADMIN_ID
        is_elite = user_data[user_id]['is_elite']
        is_normal = user_data[user_id]['is_normal']
        allowed, scans, limit = can_scan_today(user_id)

        if uid == ADMIN_ID:
            stats = f"📊 *Your Stats*\n\nStatus: ADMIN 🔧\nScans: Unlimited\nAccess: All features\nPairs: 18\nSignals sent today: {scans}"
        elif is_elite:
            expiry = user_data[user_id]['elite_expiry'][:10]
            stats = f"📊 *Your Stats*\n\nStatus: ELITE 👑\nExpires: {expiry}\nScans: Unlimited\nPairs: 18\nSignals sent today: {scans}\nAuto pings: ON\nVoice: ON"
        elif is_vip:
            expiry = user_data[user_id]['vip_expiry'][:10]
            stats = f"📊 *Your Stats*\n\nStatus: VIP 💎\nExpires: {expiry}\nScans: Unlimited\nPairs: 18\nSignals sent today: {scans}\nAuto pings: ON"
        elif is_normal:
            expiry = user_data[user_id]['normal_expiry'][:10]
            stats = f"📊 *Your Stats*\n\nStatus: Normal 💰\nExpires: {expiry}\nScans today: {scans}/{limit}\nRemaining: {limit - scans}\nAuto pings: OFF"
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
            direction_arrow = "⬆️ CALL" if sig['direction'] == 'CALL' else "⬇️ PUT"
            msg += f"{i}. {sig['pair']} {direction_arrow} {sig['grade']} - {hours}h ago\n Entry: {sig['entry_time']} | Expiry: {sig['expiry']}\n\n"
        msg += "_Win/Loss tracked by admin_"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_menu"))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

    elif call.data == "settings":
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired.")
            return
        s = user_data[user_id]['settings']
        markup = types.InlineKeyboardMarkup()
        kz_text = f"🔔 Killzone Pings: {'ON' if s['killzone_pings'] else 'OFF'}"
        conf_text = f"📊 Min Confidence: {s['min_confidence']}%"
        qh_text = f"🌙 Quiet Hours: {'ON' if s['quiet_hours'] else 'OFF'}"
        voice_text = f"🔊 Voice Alerts: {'ON' if s['voice_alerts'] else 'OFF'}"
        markup.add(types.InlineKeyboardButton(kz_text, callback_data="toggle_kz"))
        markup.add(types.InlineKeyboardButton(conf_text, callback_data="set_conf"))
        markup.add(types.InlineKeyboardButton(qh_text, callback_data="toggle_qh"))
        if user_data[user_id]['is_elite']:
            markup.add(types.InlineKeyboardButton(voice_text, callback_data="toggle_voice"))
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_menu"))
        bot.edit_message_text("⚙️ *Settings*\n\nCustomize your bot:", call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

    elif call.data == "toggle_kz":
        user_data[user_id]['settings']['killzone_pings'] = not user_data[user_id]['settings']['killzone_pings']
        save_data()
        bot.answer_callback_query(call.id, "Killzone pings toggled!")
        callback_handler(call)

    elif call.data == "set_conf":
        current = user_data[user_id]['settings']['min_confidence']
        new = 65 if current == 60 else 60
        user_data[user_id]['settings']['min_confidence'] = new
        save_data()
        bot.answer_callback_query(call.id, f"Min confidence set to {new}%")
        callback_handler(call)

    elif call.data == "toggle_qh":
        user_data[user_id]['settings']['quiet_hours'] = not user_data[user_id]['settings']['quiet_hours']
        save_data()
        bot.answer_callback_query(call.id, "Quiet hours toggled!")
        callback_handler(call)

    elif call.data == "toggle_voice":
        user_data[user_id]['settings']['voice_alerts'] = not user_data[user_id]['settings']['voice_alerts']
        save_data()
        bot.answer_callback_query(call.id, "Voice alerts toggled!")
        callback_handler(call)

    elif call.data == "back_menu":
        bot.answer_callback_query(call.id)
        if uid == ADMIN_ID:
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn1 = types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal")
            btn2 = types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats")
            btn3 = types.InlineKeyboardButton("🕐 Last 5 Signals", callback_data="last_signals")
            btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            btn5 = types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel")
            btn6 = types.InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")
            markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
            bot.edit_message_text(
                f"🔥 *Welcome Admin @Denverlyksignalpro* 🔧\n\nID: `{uid}`\nAccess: Unlimited\nPairs: 18\n\nUse signals + manage users below:",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup
            )
        else:
            markup = types.InlineKeyboardMarkup(row_width=2)
            btn1 = types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal")
            btn2 = types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats")
            btn3 = types.InlineKeyboardButton("🕐 Last 5 Signals", callback_data="last_signals")
            btn4 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            btn5 = types.InlineKeyboardButton("📊 Leaderboard", callback_data="leaderboard")
            markup.add(btn1, btn2, btn3, btn4, btn5)
            tier = "ELITE 👑" if user_data[user_id]['is_elite'] else "VIP 💎" if user_data[user_id]['is_vip'] else "Normal 💰" if user_data[user_id]['is_normal'] else "None"
            expiry_key = 'elite_expiry' if user_data[user_id]['is_elite'] else 'vip_expiry' if user_data[user_id]['is_vip'] else 'normal_expiry'
            expiry_str = user_data[user_id][expiry_key][:10] if user_data[user_id][expiry_key] else "N/A"
            bot.edit_message_text(
                f"🔥 *Welcome back {tier}*\n\nExpires: {expiry_str}\nPairs: 18\n\nSelect an option:",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup
            )

    elif call.data.startswith("scan_"):
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired. Renew to continue.")
            return

        if is_quiet_hours(user_id):
            bot.answer_callback_query(call.id, "Quiet hours active. No signals 10PM-7AM EAT.")
            return

        allowed, scans, limit = can_scan_today(user_id)
        if not allowed:
            bot.answer_callback_query(call.id, f"Daily limit {limit} reached. Upgrade to VIP for unlimited.")
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💎 Upgrade to VIP", callback_data="choose_vip"))
            markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu"))
            bot.edit_message_text(
                f"🚫 *Daily Limit Reached*\n\nYou've used {scans}/{limit} scans today.\n\nNormal: 10/day\nVIP: Unlimited + 60s early alerts",
                call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup
            )
            return

        pair = call.data.replace("scan_", "")
        is_vip = user_data[user_id]['is_vip'] or uid == ADMIN_ID
        is_elite = user_data[user_id]['is_elite']
        user_min_conf = user_data[user_id]['settings']['min_confidence']

        bot.answer_callback_query(call.id, f"Scanning {pair}... {scans+1}/{limit}")
        bot.edit_message_text(f"🔍 Scanning {pair} for B+ setup...\n\nScans today: {scans+1}/{limit}", call.message.chat.id, call.message.message_id)

        signal = analyze_pocket_pair(pair, is_vip, user_min_conf)

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Scan Again", callback_data="get_signal"))
        markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu"))

        if signal:
            user_data[user_id]['scans_today'] += 1
            save_signal_to_history(user_id, signal)
            save_data()
            signal_text = format_pocket_signal(signal, is_vip, is_elite)
            remaining = limit - user_data[user_id]['scans_today']
            footer = f"\n\n_Scans left today: {remaining}_" if limit!= 999 else ""
            bot.edit_message_text(signal_text + footer, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)
            if signal['grade'] == 'A+':
                asyncio.run(log_signal_sent(signal['pair'], signal['direction'], signal['confidence'],
                                          signal['entry_time'], signal['df_1m'], signal['confluence']))
        else:
            bot.edit_message_text(f"❌ No B+ setup on {pair} right now.\n\nKillzone active but need 3/5 confluences.\n\n_Scan not counted. {limit - scans} left today._", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data == "leaderboard":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id, msg_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
                self.message_id = msg_id
        show_leaderboard(FakeMsg(uid, call.message.chat.id, call.message.message_id))

    # Admin panel callbacks
    elif call.data == "admin_listusers":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id, msg_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
                self.message_id = msg_id
        cmd_listusers(FakeMsg(uid, call.message.chat.id, call.message.message_id))

    elif call.data == "admin_addvip":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Send: `/adduser USER_ID VIP`\nExample: `/adduser 123456789 VIP`", parse_mode='Markdown')

    elif call.data == "admin_addelite":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Send: `/adduser USER_ID ELITE`\nExample: `/adduser 123456789 ELITE`", parse_mode='Markdown')

    elif call.data == "admin_renewvip":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Send: `/renewuser USER_ID DAYS`\nExample: `/renewuser 123456789 7`", parse_mode='Markdown')

    elif call.data == "admin_broadcast":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Send: `/broadcast YOUR MESSAGE`", parse_mode='Markdown')

    elif call.data == "admin_stats":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id, msg_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
                self.message_id = msg_id
        cmd_stats(FakeMsg(uid, call.message.chat.id, call.message.message_id))

    elif call.data == "admin_panel":
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📂 List Users", callback_data="admin_listusers"),
            types.InlineKeyboardButton("➕ Add VIP", callback_data="admin_addvip"),
            types.InlineKeyboardButton("👑 Add Elite", callback_data="admin_addelite"),
            types.InlineKeyboardButton("🔄 Renew User", callback_data="admin_renewvip"),
            types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            types.InlineKeyboardButton("🔥 Bot Stats", callback_data="admin_stats"),
            types.InlineKeyboardButton("🚀 Test Auto Ping", callback_data="admin_testping"),
            types.InlineKeyboardButton("📊 Signal Stats", callback_data="bot_stats"),
            types.InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")
        )
        bot.edit_message_text(
            f"🔧 *ADMIN PANEL* 🔧\n\nWelcome @Denverlyksignalpro\n\nID: `{uid}`\nTotal Users: `{len(USERS_DATA)}`\nPairs: 18",
            call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup
        )

    elif call.data == "admin_testping":
        bot.answer_callback_query(call.id, "🚀 Triggering test auto ping...")
        auto_scan_pocket_vip()

    elif call.data == "bot_stats":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id, msg_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
                self.message_id = msg_id
        show_bot_stats(FakeMsg(uid, call.message.chat.id, call.message.message_id))

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

Activate: `/adduser {user_id} VIP` or `/adduser {user_id} ELITE`
"""
    try:
        bot.send_message(ADMIN_ID, alert_msg, parse_mode='Markdown')
    except:
        print(f"Failed to alert admin for {user_id}")

# ===== SCHEDULED JOBS =====
def killzone_ping():
    for uid in user_data:
        if (user_data[uid]['is_vip'] or user_data[uid]['is_elite'] or int(uid) == ADMIN_ID) and user_data[uid]['settings']['killzone_pings'] and not is_quiet_hours(uid):
            try:
                bot.send_message(int(uid), "🎯 *Killzone Active*\n\nLondon/NY session is live. Bot scanning 18 pairs for A+ entries...", parse_mode='Markdown')
            except:
                pass

def sunday_outlook():
    msg = "📈 *Sunday Weekly Outlook*\n\nKey levels to watch this week:\nXAUUSD_OTC: 2630 support, 2670 resistance\nEURUSD_OTC: 1.0850 key zone\n\nBot is live on 18 pairs. Good luck this week VIP 💎"
    for uid in user_data:
        if user_data[uid]['is_vip'] or user_data[uid]['is_elite'] or int(uid) == ADMIN_ID:
            try:
                bot.send_message(int(uid), msg, parse_mode='Markdown')
            except:
                pass

def run_schedule():
    schedule.every().day.at("07:00").do(killzone_ping) # 10:00 EAT
    schedule.every().day.at("12:00").do(killzone_ping) # 15:00 EAT
    schedule.every().day.at("07:01").do(auto_scan_pocket_vip) # 10:01 EAT auto scan
    schedule.every().day.at("12:31").do(auto_scan_pocket_vip) # 15:31 EAT auto scan
    schedule.every().sunday.at("17:00").do(sunday_outlook)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ===== START BOT =====
if __name__ == "__main__":
    load_data()
    print(f"Bot online: @Denverlykbot")
    print(f"Admin: {ADMIN_ID}")
    print(f"M-Pesa: {MPESA_NUMBER}")
    print(f"Pairs loaded: {len(PAIRS)}")

    # Start expiry checker - runs every hour
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_expired_vips, 'interval', hours=1)
    scheduler.start()
    print("=== EXPIRY SCHEDULER STARTED ===", flush=True)

    # Run once on startup
    check_expired_vips()

    threading.Thread(target=run_schedule, daemon=True).start()
    print("=== SCHEDULE THREAD STARTED ===", flush=True)
    print("=== BOT POLLING STARTED ===", flush=True)
    bot.infinity_polling()
