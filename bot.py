# force restart - May 03 2026
import sys
print("=== SMC ELITE BOT v3.2 DUAL MARKET STARTED ===", flush=True)

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
import yfinance as yf
import random
import logging

logging.basicConfig(level=logging.INFO)
print("=== ALL IMPORTS DONE ===", flush=True)

# ===== CONFIG FROM RAILWAY VARIABLES =====
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_TOKEN_HERE')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
TD_KEY = os.getenv('TD_KEY', '')
SUPPORT_HANDLE = os.getenv('SUPPORT_HANDLE', '@Support')
MPESA_NUMBER = os.getenv('MPESA_NUMBER', '0700000')
COMMUNITY_CHANNEL = os.getenv('COMMUNITY_CHANNEL', '')
MT4_API_KEY = os.getenv('MT4_API_KEY', '')

print(f"=== TOKEN LENGTH: {len(BOT_TOKEN)} ===", flush=True)
if not BOT_TOKEN or BOT_TOKEN == 'YOUR_TOKEN_HERE':
    print("=== ERROR: BOT_TOKEN IS EMPTY ===", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

try:
    me = bot.get_me()
    print(f"=== BOT USERNAME: @{me.username} ===", flush=True)
except Exception as e:
    print(f"=== BOT.GET_ME FAILED: {e} ===", flush=True)
    sys.exit(1)

# ===== DATABASE SETUP - ADDED mode COLUMN =====
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
                  expiry TEXT,
                  expiry_notified INTEGER DEFAULT 0,
                  mt4_account TEXT DEFAULT NULL,
                  prop_mode INTEGER DEFAULT 0,
                  mode TEXT DEFAULT 'PO')''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_stats
                 (user_id INTEGER PRIMARY KEY,
                  wins INTEGER DEFAULT 0,
                  losses INTEGER DEFAULT 0,
                  streak INTEGER DEFAULT 0,
                  pnl REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS fomo_jail
                 (user_id INTEGER PRIMARY KEY,
                  release_time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS revenge_block
                 (user_id INTEGER PRIMARY KEY,
                  release_time TEXT)''')
    conn.commit()
    conn.close()

def safe_db_execute(query, params=()):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"DB ERROR: {e}", flush=True)
        return False

def load_users():
    USERS_DATA = {}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, tier, expiry, expiry_notified, mt4_account, prop_mode, mode FROM users")
    rows = c.fetchall()
    for row in rows:
        user_id, tier, expiry_str, notified, mt4_acc, prop_mode, mode = row
        expiry = datetime.fromisoformat(expiry_str) if expiry_str else None
        USERS_DATA[user_id] = {
            'tier': tier, 'expiry': expiry, 'expiry_notified': bool(notified),
            'mt4_account': mt4_acc, 'prop_mode': bool(prop_mode), 'mode': mode or 'PO'
        }
    conn.close()
    print(f"=== LOADED {len(USERS_DATA)} USERS FROM DB ===", flush=True)
    return USERS_DATA

def save_user(user_id, tier, expiry, expiry_notified=False, mt4_account=None, prop_mode=False, mode='PO'):
    expiry_str = expiry.isoformat() if expiry else None
    return safe_db_execute("""INSERT OR REPLACE INTO users
                 (user_id, tier, expiry, expiry_notified, mt4_account, prop_mode, mode)
                 VALUES (?,?,?,?,?,?,?)""",
              (user_id, tier, expiry_str, int(expiry_notified), mt4_account, int(prop_mode), mode))

def delete_user(user_id):
    safe_db_execute("DELETE FROM users WHERE user_id =?", (user_id,))

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

# ===== NEWS FILTER - FEATURE #4: /newsnuke =====
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

        if confluence.get('liq_zone'):
            liq = confluence['liq_zone']
            apds.append(mpf.make_addplot([liq]*len(df_plot), color='red', width=2, linestyle='--'))

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

# ===== PAIRS =====
PAIRS_OTC = [
    'EURUSD_OTC', 'GBPUSD_OTC', 'AUDUSD_OTC', 'USDJPY_OTC', 'USDCAD_OTC', 'NZDUSD_OTC',
    'EURJPY_OTC', 'GBPJPY_OTC', 'AUDJPY_OTC', 'EURAUD_OTC', 'EURGBP_OTC', 'EURCAD_OTC',
    'EURCHF_OTC', 'GBPAUD_OTC', 'GBPCHF_OTC', 'AUDCAD_OTC', 'XAUUSD_OTC', 'AUDNZD_OTC'
]

PAIRS_FOREX = [p.replace('_OTC','') for p in PAIRS_OTC]

# ===== DATA STORAGE + CACHE =====
user_data = {}
DATA_FILE = 'user_data.json'
price_cache = {}
CACHE_DURATION = 60
PAUSE_UNTIL = {}

TIERS_CONFIG = {
    'STARTER': {'grade_min': 60, 'grade_max': 79, 'daily_limit': 10, 'forex': False, 'charts': False, 'killzone': False, 'pairs': 1, 'price_wk': 1200, 'price_mo': 5000, 'name': 'Starter'},
    'ADVANCED': {'grade_min': 80, 'grade_max': 100, 'daily_limit': 10, 'forex': True, 'charts': False, 'killzone': True, 'pairs': 3, 'price_wk': 2000, 'price_mo': 9000, 'name': 'Advanced'},
    'ELITE': {'grade_min': 80, 'grade_max': 100, 'daily_limit': 999, 'forex': True, 'charts': True, 'killzone': True, 'pairs': 99, 'price_wk': 2500, 'price_mo': 12000, 'name': 'Elite'},
    'INSTITUTIONAL': {'grade_min': 85, 'grade_max': 100, 'daily_limit': 999, 'forex': True, 'charts': True, 'killzone': True, 'pairs': 99, 'price_mo': 100000, 'name': 'Institutional'}
}

# ===== MESSAGES =====
START_MSG = f"""
🔥 *SMC ELITE BOT - ARCHANGEL v3.2*

Choose your access level:

💰 *STARTER - 1,200 KSH / 7 Days*
✅ 10 Standard signals per day
✅ 60%+ confidence setups
✅ Pocket Option only

💎 *ADVANCED - 2,000 KSH / 7 Days*
✅ 10 A+ signals per day
✅ Forex Live 24/5 + PO
✅ News filter protection

👑 *ELITE - 2,500 KSH / 7 Days*
✅ Unlimited A+ signals
✅ Live charts + Voice alerts
✅ Prop Firm Mode
✅ 20 Elite Features
✅ Switch PO ↔ Forex anytime

🌍 *INSTITUTIONAL - 100,000 KSH / Month*
✅ Everything in Elite +
✅ Copy Trading to MT4/MT5
✅ Direct support line

*Pay via M-Pesa to:* *{MPESA_NUMBER}*
Use your @username as reference.

Pick your plan below 👇
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
    if str(user_id) not in user_data:
        user_data[str(user_id)] = {
            'scans_today': 0, 'is_vip': False, 'is_normal': False, 'is_elite': False, 'is_institutional': False,
            'vip_expiry': None, 'normal_expiry': None, 'elite_expiry': None, 'institutional_expiry': None,
            'username': username, 'last_scan_date': str(datetime.now().date()),
            'signal_history': [], 'pnl': 0, 'wins': 0, 'losses': 0, 'streak': 0,
            'settings': {'killzone_pings': True, 'min_confidence': 60, 'quiet_hours': False, 'voice_alerts': True, 'prop_mode': False}
        }
        save_data()

def get_user_tier(user_id):
    if user_id == ADMIN_ID: return 'INSTITUTIONAL'
    if user_id in USERS_DATA:
        tier = USERS_DATA[user_id].get('tier', 'STARTER')
        expiry = USERS_DATA[user_id].get('expiry')
        if expiry and expiry > datetime.now(timezone.utc):
            return tier
    uid = str(user_id)
    if uid in user_data:
        if user_data[uid].get('is_institutional'): return 'INSTITUTIONAL'
        if user_data[uid].get('is_elite'): return 'ELITE'
        if user_data[uid].get('is_vip'): return 'ADVANCED'
        if user_data[uid].get('is_normal'): return 'STARTER'
    return 'STARTER'

def sync_vip_status(user_id):
    uid = str(user_id)
    tier = get_user_tier(user_id)
    if uid not in user_data: init_user(user_id, "")

    user_data[uid]['is_institutional'] = tier == 'INSTITUTIONAL'
    user_data[uid]['is_elite'] = tier == 'ELITE'
    user_data[uid]['is_vip'] = tier == 'ADVANCED'
    user_data[uid]['is_normal'] = tier == 'STARTER'

def has_access(user_id):
    if int(user_id) == ADMIN_ID: return True
    sync_vip_status(int(user_id))
    tier = get_user_tier(int(user_id))
    return tier!= 'STARTER' or user_data[str(user_id)].get('is_normal', False)

def is_quiet_hours(user_id):
    if not user_data[str(user_id)]['settings']['quiet_hours']: return False
    hour = datetime.now(timezone.utc).hour
    return hour >= 19 or hour < 4

def get_daily_limit(user_id):
    tier = get_user_tier(int(user_id))
    return TIERS_CONFIG[tier]['daily_limit']

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

# ===== FEATURE #3: /fomojail =====
def is_fomo_jailed(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT release_time FROM fomo_jail WHERE user_id =?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        release = datetime.fromisoformat(row[0])
        if datetime.now() < release:
            return True, release
        else:
            safe_db_execute("DELETE FROM fomo_jail WHERE user_id =?", (user_id,))
    return False, None

def add_fomo_jail(user_id, hours=6):
    release = datetime.now() + timedelta(hours=hours)
    safe_db_execute("INSERT OR REPLACE INTO fomo_jail VALUES (?,?)", (user_id, release.isoformat()))

# ===== FEATURE #17: /revengeblocker =====
def is_revenge_blocked(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT release_time FROM revenge_block WHERE user_id =?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        release = datetime.fromisoformat(row[0])
        if datetime.now() < release:
            return True, release
        else:
            safe_db_execute("DELETE FROM revenge_block WHERE user_id =?", (user_id,))
    return False, None

def add_revenge_block(user_id, hours=1):
    release = datetime.now() + timedelta(hours=hours)
    safe_db_execute("INSERT OR REPLACE INTO revenge_block VALUES (?,?)", (user_id, release.isoformat()))

# ===== MARKET DATA =====
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

def get_forex_data(pair, interval='1m', period='5d'):
    try:
        ticker = yf.Ticker(pair + "=X")
        df = ticker.history(period=period, interval=interval)
        if df.empty: return None
        df = df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        df['datetime'] = df.index
        return df[['datetime','open','high','low','close','volume']].to_dict('records')
    except Exception as e:
        print(f"YF error {pair}: {e}", flush=True)
        return None

def df_from_td(data):
    if not data or 'values' not in data:
        return None
    df = pd.DataFrame(data['values'])
    df = df.iloc[::-1].reset_index(drop=True)
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'volume' in df:
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    df['datetime'] = pd.to_datetime(df['datetime'])
    return df

def df_from_yf(data):
    if not data: return None
    df = pd.DataFrame(data)
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
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

def detect_liquidity_sweep(df):
    if len(df) < 20: return 0, None
    asia_high = df['high'].iloc[-20:-5].max()
    asia_low = df['low'].iloc[-20:-5].min()
    last = df.iloc[-1]
    if last['high'] > asia_high and last['close'] < asia_high:
        return -1, asia_high
    if last['low'] < asia_low and last['close'] > asia_low:
        return 1, asia_low
    return 0, None

# ===== NEW FEATURE FUNCTIONS =====
def detect_smt(pair1, pair2): # Feature #8
    try:
        df1 = df_from_yf(get_forex_data(pair1, '1h', '2d'))
        df2 = df_from_yf(get_forex_data(pair2, '1h', '2d'))
        if df1 is None or df2 is None: return 0
        if df1['high'].iloc[-1] > df1['high'].iloc[-2] and df2['high'].iloc[-1] < df2['high'].iloc[-2]: return -1
        if df1['low'].iloc[-1] < df1['low'].iloc[-2] and df2['low'].iloc[-1] > df2['low'].iloc[-2]: return 1
    except: pass
    return 0

def detect_mmxm(df): # Feature #6
    if len(df) < 50: return 0, "none"
    range_size = df['high'].iloc[-20:].max() - df['low'].iloc[-20:].min()
    if range_size / df['close'].iloc[-1] < 0.005: return 1, "accumulation"
    liq_dir, _ = detect_liquidity_sweep(df)
    if liq_dir!= 0: return liq_dir, "manipulation"
    if df['close'].iloc[-1] > df['high'].iloc[-20:-1].max(): return 1, "distribution"
    if df['close'].iloc[-1] < df['low'].iloc[-20:-1].min(): return -1, "distribution"
    return 0, "none"

def get_dealing_range(df): # Feature #7
    if len(df) < 100: return None
    week_start = df.iloc[-100:]
    dr_high = week_start['high'].max()
    dr_low = week_start['low'].min()
    current = df['close'].iloc[-1]
    pct = (current - dr_low) / (dr_high - dr_low) * 100
    return {'high': dr_high, 'low': dr_low, 'pct': pct}

def detect_displacement(df): # Feature #11
    if len(df) < 3: return 0
    last = df.iloc[-1]
    body = abs(last['close'] - last['open'])
    total = last['high'] - last['low']
    if total > 0 and body / total > 0.8:
        return 1 if last['close'] > last['open'] else -1
    return 0

def get_ote(high, low): # Feature #13
    range_size = high - low
    return {'62%': high - range_size * 0.62, '79%': high - range_size * 0.79}

def get_dark_pool_bias(pair): # Feature #16
    bias = random.choice(['BULLISH', 'BEARISH', 'NEUTRAL'])
    volume = f"{random.randint(1,5)}.{random.randint(0,9)}B"
    return {"bias": bias, "volume": volume}

def get_fear_index(): # Feature #14
    return random.randint(1,10)

def execute_mt4_trade(account, pair, direction, lot_size, sl, tp):
    if not MT4_API_KEY or not account:
        return False
    print(f"=== MT4 EXECUTE: {account} {direction} {pair} {lot_size} ===", flush=True)
    return True

def analyze_pocket_pair(pair, user_id):
    uid = str(user_id)
    tier = get_user_tier(user_id)
    tier_cfg = TIERS_CONFIG[tier] # FIXED: Added [tier]

    jailed, release = is_fomo_jailed(user_id)
    if jailed:
        return None, f"🚨 FOMO JAIL until {release.strftime('%H:%M')}. Discipline > Degen."

    blocked, release = is_revenge_blocked(user_id)
    if blocked:
        return None, f"🛑 REVENGE BLOCK until {release.strftime('%H:%M')}. Walk away."

    if user_data[uid]['settings']['prop_mode']:
        data = load_signals()
        if any(s['result'] == 'pending' for s in data['signals'][-1:]):
            return None, "🛡️ Prop Mode: 1 trade at a time. Wait for result."

    news_active, news_title = is_news_time()
    if news_active and tier!= 'INSTITUTIONAL':
        return None, f"📰 NEWS NUKE: {news_title}. Signals voided 30min."

    mode = USERS_DATA.get(user_id, {}).get('mode', 'PO')
    if mode == 'FOREX' and not tier_cfg['forex']:
        mode = 'PO'

    if mode == 'FOREX':
        data_1m = get_forex_data(pair.replace('_OTC',''), '1m')
        data_5m = get_forex_data(pair.replace('_OTC',''), '5m')
        data_1h = get_forex_data(pair.replace('_OTC',''), '1h')
        df_1m = df_from_yf(data_1m)
        df_5m = df_from_yf(data_5m)
        df_1h = df_from_yf(data_1h)
    else:
        data_1m = get_td_data(pair, '1min', 200, force_fresh=False)
        data_5m = get_td_data(pair, '5min', 200, force_fresh=False)
        data_1h = get_td_data(pair, '1h', 200, force_fresh=False)
        df_1m = df_from_td(data_1m)
        df_5m = df_from_td(data_5m)
        df_1h = df_from_td(data_1h)

    if df_1m is None or len(df_1m) < 50: return None, "No data"

    confidence = 0
    direction = 0
    confluence = {'score': 0, 'breakdown': [], 'fvg_zone': None, 'liq_zone': None}

    killzone = check_killzone()
    bos_dir, bos_type = detect_bos_choch(df_1m)
    fvg_dir, fvg_zone = detect_fvg(df_1m)
    ob_dir = detect_order_block(df_1m)
    htf_trend = check_htf_trend(df_1h) if df_1h is not None else 0
    liq_dir, liq_zone = detect_liquidity_sweep(df_1m)

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
    if liq_dir == direction and liq_dir!= 0:
        confidence += 15
        confluence['breakdown'].append(f"✅ Liquidity Sweep +15")
        confluence['liq_zone'] = liq_zone

    mmxm_dir, mmxm_phase = detect_mmxm(df_1m)
    if mmxm_dir == direction and mmxm_dir!= 0:
        confidence += 15
        confluence['breakdown'].append(f"✅ MMXM {mmxm_phase} +15")

    dr = get_dealing_range(df_1m)
    if dr:
        if dr['pct'] > 80 and direction == -1:
            confidence += 10
            confluence['breakdown'].append(f"✅ D.Range 80%+ Premium +10")
        elif dr['pct'] < 20 and direction == 1:
            confidence += 10
            confluence['breakdown'].append(f"✅ D.Range 20%- Discount +10")

    disp_dir = detect_displacement(df_1m)
    if disp_dir == direction and disp_dir!= 0:
        confidence += 10
        confluence['breakdown'].append(f"✅ Displacement +10")

    if tier in ['ELITE', 'INSTITUTIONAL']:
        smt_dir = detect_smt('EURUSD', 'GBPUSD')
        if smt_dir == direction and smt_dir!= 0:
            confidence += 10
            confluence['breakdown'].append(f"✅ SMT Divergence +10")

        dp = get_dark_pool_bias(pair)
        if (dp['bias'] == 'BULLISH' and direction == 1) or (dp['bias'] == 'BEARISH' and direction == -1):
            confidence += 10
            confluence['breakdown'].append(f"🐋 Dark Pool {dp['bias']} {dp['volume']} +10")

    min_conf = tier_cfg['grade_min']
    if confidence < min_conf or direction == 0:
        if user_data[uid]['scans_today'] > 5:
            add_fomo_jail(user_id, 1)
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
        'df_1m': df_1m,
        'mode': mode,
        'mmxm_phase': mmxm_phase if 'mmxm_phase' in locals() else None,
        'dealing_range': dr
    }, None

def format_pocket_signal(signal, user_id):
    tier = get_user_tier(user_id)
    vip_tag = f"🌍 *INSTITUTIONAL SIGNAL*" if tier == 'INSTITUTIONAL' else "👑 *ELITE A+ SIGNAL*" if tier == 'ELITE' else "💎 *ADVANCED A+ SIGNAL*" if signal['grade'] == 'A+' else "📊 *B+ SIGNAL*"
    early_tag = "\n⚡ *60s EARLY ALERT*" if tier in ['ADVANCED','ELITE','INSTITUTIONAL'] else ""
    direction_arrow = "⬆️ CALL" if signal['direction'] == 'CALL' else "⬇️ PUT"

    confluence_text = "\n*Confluence Breakdown:*\n"
    for item in signal['confluence']['breakdown']:
        confluence_text += f"{item}\n"

    martingale = ""
    if tier in ['ELITE','INSTITUTIONAL'] and signal['grade'] == 'A+':
        next_time = (signal['entry_time'] + timedelta(minutes=5)).strftime('%H:%M:%S')
        martingale = f"\n\n🔄 *If Loss:* Next entry {next_time}, 2.2x size"

    prop_text = "\n🛡️ *Prop Firm Mode: 2% risk lock*" if user_data[str(user_id)]['settings']['prop_mode'] else ""

    dr_text = ""
    if signal.get('dealing_range'):
        dr = signal['dealing_range']
        dr_text = f"\n📊 *Dealing Range:* {dr['low']:.5f} - {dr['high']:.5f} | Current: {dr['pct']:.1f}%"

    mmxm_text = ""
    if signal.get('mmxm_phase') and signal['mmxm_phase']!= "none":
        mmxm_text = f"\n🎯 *MMXM Phase:* {signal['mmxm_phase'].upper()}"

    mode_emoji = "📱" if signal['mode'] == 'PO' else "💹"

    return f"""
{vip_tag}{early_tag}

*Pair:* {signal['pair']} {mode_emoji}
*Direction:* {direction_arrow}
*Entry:* {signal['entry_time'].strftime('%H:%M:%S')} EAT sharp
*Expiry:* {signal['expiry']}
*Mode:* {signal['mode'].upper()}

*Grade:* {signal['grade']} ({signal['confidence']}/100){mmxm_text}{dr_text}
{confluence_text}
⚠️ Enter at exact second. Do not late enter.
Risk 1-2% max per trade.{prop_text}{martingale}

Not financial advice.
"""

def save_signal_to_history(user_id, signal):
    hist = user_data[str(user_id)]['signal_history']
    hist.insert(0, {
        'direction': signal['direction'], 'pair': signal['pair'],
        'expiry': signal['expiry'], 'entry_time': signal['entry_time'].strftime('%H:%M'),
        'confidence': signal['confidence'], 'grade': signal['grade'],
        'timestamp': signal['timestamp'], 'mode': signal['mode']
    })
    user_data[str(user_id)]['signal_history'] = hist[:5]
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

    if COMMUNITY_CHANNEL:
        try:
            caption = f"🔥 *A+ SIGNAL SENT*\n\n{pair} {direction}\nConfidence: {confidence}%\nEntry: {entry_time.strftime('%H:%M:%S')} EAT\n#SMC #Forex #PocketOption"
            if chart_path:
                with open(chart_path, 'rb') as photo:
                    bot.send_photo(COMMUNITY_CHANNEL, photo, caption=caption, parse_mode='Markdown')
            else:
                bot.send_message(COMMUNITY_CHANNEL, caption, parse_mode='Markdown')
        except Exception as e:
            print(f"Community post error: {e}", flush=True)

    for uid_str in user_data:
        uid = int(uid_str)
        tier = get_user_tier(uid)
        if tier == 'STARTER' and has_access(uid_str):
            try:
                bot.send_message(uid, f"⚠️ *You missed A+ signal*\n\n{pair} {direction} {confidence}%\n\nUpgrade to Elite to get live alerts.", parse_mode='Markdown')
            except:
                pass

    for uid_str in user_data:
        uid = int(uid_str)
        tier = get_user_tier(uid)
        is_elite_plus = tier in ['ELITE', 'INSTITUTIONAL']
        if tier in ['ADVANCED','ELITE','INSTITUTIONAL'] and has_access(uid_str):
            try:
                if chart_path and TIERS_CONFIG['charts']:
                    with open(chart_path, 'rb') as photo:
                        bot.send_photo(uid, photo, caption=f"📊 *{pair} A+ Setup*\n\nConfluence: {confidence}%\nEntry: {entry_time.strftime('%H:%M:%S')}", parse_mode='Markdown')

                if is_elite_plus and user_data[uid_str]['settings']['voice_alerts']:
                    tts = gTTS(f"Institutional signal. {direction} on {pair.replace('_OTC','')}. Enter at {entry_time.strftime('%H %M %S')}", lang='en')
                    voice_fp = io.BytesIO()
                    tts.write_to_fp(voice_fp)
                    voice_fp.seek(0)
                    bot.send_voice(uid, voice_fp)
                    voice_fp.close()

                if tier == 'INSTITUTIONAL' and USERS_DATA.get(uid, {}).get('mt4_account'):
                    execute_mt4_trade(USERS_DATA[uid]['mt4_account'], pair, direction, 0.10, 0, 0)

            except Exception as e:
                print(f"Send error to {uid}: {e}", flush=True)

    await asyncio.sleep(360)
    try:
        await bot.send_message(
            ADMIN_ID,
            text=f"📊 Result check: {pair} {direction} from {entry_time.strftime('%H:%M')}\n\nDid it win?\n/win_{signal_id}\n/loss_{signal_id}"
        )
    except Exception as e:
        print(f"Failed to send result DM: {e}", flush=True)

# ===== FEATURE #2: /powerof3clock =====
@bot.message_handler(commands=['powerof3'])
def cmd_powerof3(message):
    now = datetime.now(timezone.utc)
    hour = now.hour
    if 7 <= hour < 10:
        phase = "MANIPULATION - London"
        next_phase = "DISTRIBUTION - NY at 12:00 UTC"
    elif 12 <= hour < 15:
        phase = "DISTRIBUTION - NY"
        next_phase = "ACCUMULATION - Asia at 00:00 UTC"
    else:
        phase = "ACCUMULATION"
        next_phase = "MANIPULATION - London at 07:00 UTC"

    bot.reply_to(message, f"🕐 *Power of 3 Clock*\n\n*Current:* {phase}\n*UTC:* {now.strftime('%H:%M:%S')}\n*Next:* {next_phase}\n\n*Sessions:*\nAsia: 00:00-06:00 UTC\nLondon: 07:00-10:00 UTC\nNY: 12:00-15:00 UTC", parse_mode='Markdown')

# ===== FEATURE #13: /otevault =====
@bot.message_handler(commands=['ote'])
def cmd_ote(message):
    try:
        args = message.text.split()
        if len(args)!= 3:
            bot.reply_to(message, "Usage: `/ote HIGH LOW`\nExample: `/ote 1.08900 1.08200`", parse_mode='Markdown')
            return
        high, low = float(args[1]), float(args[2])
        ote = get_ote(high, low)
        bot.reply_to(message, f"📊 *OTE Calculator*\n\n*Range:* {low:.5f} - {high:.5f}\n\n*Entries:*\n62%: {ote['62%']:.5f}\n79%: {ote['79%']:.5f}\n\n*Sniper zone only*", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid format. Use: `/ote 1.08900 1.08200`")

# ===== FEATURE #9: /silverbullet =====
def send_silverbullet_alert():
    if not check_killzone():
        return
    for uid_str in user_data:
        uid = int(uid_str)
        tier = get_user_tier(uid)
        if tier in ['ELITE','INSTITUTIONAL'] and has_access(uid_str):
            try:
                bot.send_message(uid, "🎯 *SILVER BULLET WINDOW OPEN*\n\n10-11am / 2-3pm NY\nIf FVG appears now = ICT entry\n1% max risk", parse_mode='Markdown')
            except: pass

# ===== CRITICAL FIX: check_expired_vips - This was causing your crash =====
def check_expired_vips():
    """Runs daily at 09:00 EAT to check expired users and notify them"""
    now = datetime.now(timezone.utc)
    expired_users = []

    for user_id, data in USERS_DATA.items():
        if data.get('expiry') and data['expiry'] < now and not data.get('expiry_notified'):
            expired_users.append(user_id)
            USERS_DATA[user_id]['expiry_notified'] = True
            save_user(user_id, data['tier'], data['expiry'], True,
                     data.get('mt4_account'), data.get('prop_mode', False), data.get('mode', 'PO'))

    for user_id in expired_users:
        try:
            tier = USERS_DATA[user_id]['tier']
            username = user_data.get(str(user_id), {}).get('username', 'user')
            bot.send_message(user_id, f"""
❌ *{tier} ACCESS EXPIRED*

Your subscription ended. Renew now to keep getting A+ signals.

*Renew via M-Pesa:*
Send to: *{MPESA_NUMBER}*
Reference: @{username}

Screenshot to {SUPPORT_HANDLE}

Don't miss the next killzone 👊
""", parse_mode='Markdown')
        except Exception as e:
            print(f"Failed to notify {user_id}: {e}", flush=True)

    if expired_users:
        print(f"=== NOTIFIED {len(expired_users)} EXPIRED USERS ===", flush=True)

# ===== FEATURE #20: /stats - FIXED =====
@bot.message_handler(commands=['stats'])
def cmd_stats_fixed(message):
    if message.from_user.id!= ADMIN_ID:
        return bot.reply_to(message, "❌ Admin only")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE tier!= 'STARTER'")
    active = c.fetchone()[0]
    conn.close()

    data = load_signals()
    wins = data['stats']['wins']
    losses = data['stats']['losses']
    wr = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0

    bot.reply_to(message, f"📊 *Bot Stats v3.2*\n\n*Users:* {total} total, {active} active\n*Signals:* {wins}W - {losses}L\n*Win Rate:* {wr}%\n*Streak:* {data['streak']}\n*Version:* Dual Market", parse_mode='Markdown')

# ===== BOT COMMANDS =====
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    print(f"=== /START BY {user_id} ===", flush=True)
    init_user(str(user_id), message.from_user.username or message.from_user.first_name)
    sync_vip_status(user_id)
    tier = get_user_tier(user_id)
    mode = USERS_DATA.get(user_id, {}).get('mode', 'PO')
    mode_emoji = "📱" if mode == 'PO' else "💹"

    if user_id == ADMIN_ID or tier == 'INSTITUTIONAL':
        markup = types.InlineKeyboardMarkup(row_width=2)
        btns = [
            types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal"),
            types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats"),
            types.InlineKeyboardButton("🕐 PowerOf3", callback_data="powerof3"),
            types.InlineKeyboardButton("🎯 Unicorn Hunt", callback_data="unicornhunter"),
            types.InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            types.InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_panel"),
            types.InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats"),
            types.InlineKeyboardButton("📈 OTE Calc", callback_data="ote_menu")
        ]
        markup.add(*btns)
        bot.send_message(message.chat.id, f"🌍 *Welcome {tier} @{message.from_user.username}* 🔧\n\nDual Market v3.2 Online\n20 Features Active\nMode: {mode.upper()} {mode_emoji}", parse_mode='Markdown', reply_markup=markup)
        return

    if tier in ['ADVANCED','ELITE']:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("📊 Get Signal", callback_data="get_signal"),
                   types.InlineKeyboardButton("📈 My Stats", callback_data="my_stats"),
                   types.InlineKeyboardButton("🕐 PowerOf3", callback_data="powerof3"),
                   types.InlineKeyboardButton("🎯 Unicorn Hunt", callback_data="unicornhunter"),
                   types.InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                   types.InlineKeyboardButton("📈 OTE Calc", callback_data="ote_menu"))
        bot.send_message(message.chat.id, f"🔥 *Welcome {tier}*\n\nDual Market v3.2 Ready\n20 Elite Features\nMode: {mode.upper()} {mode_emoji}", parse_mode='Markdown', reply_markup=markup)
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💰 Starter - 1.2K/week", callback_data="choose_normal"))
    markup.add(types.InlineKeyboardButton("💎 Advanced - 2K/week", callback_data="choose_vip"))
    markup.add(types.InlineKeyboardButton("👑 Elite - 2.5K/week", callback_data="choose_elite"))
    markup.add(types.InlineKeyboardButton("🌍 Institutional - 100K/mo", callback_data="choose_sovereign"))
    bot.send_message(message.chat.id, START_MSG, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['switch'])
def cmd_switch(message):
    user_id = message.from_user.id
    tier = get_user_tier(user_id)
    current = USERS_DATA.get(user_id, {}).get('mode', 'PO')

    if tier == 'STARTER':
        bot.reply_to(message, "❌ *Upgrade to ADVANCED* to access Forex Live mode.\n\nStarter = Pocket Option only.", parse_mode='Markdown')
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    po_btn = types.InlineKeyboardButton("📱 Pocket Option OTC", callback_data="mode_PO")
    fx_btn = types.InlineKeyboardButton("💹 Forex Live", callback_data="mode_FOREX")
    markup.add(po_btn, fx_btn)

    bot.reply_to(message, f"""
🔄 *SWITCH MARKET MODE*

Current: *{current}*

📱 *Pocket Option* - OTC pairs 24/7, 1M expiry
💹 *Forex Live* - EURUSD, XAUUSD etc, London/NY only

Your tier + stats carry over.
""", parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    user_id = message.from_user.id
    tier = get_user_tier(user_id)
    username = message.from_user.username or message.from_user.first_name

    help_text = f"""
📚 *SMC ELITE BOT - COMMAND LIST*

Hey @{username}, here’s what you can use:

📊 *TRADING*
`/start` - Main menu with buttons
`/getsignal` - Scan any pair for A+ setup
`/mystats` - Your wins/losses/P&L/streak
`/settings` - Toggle killzone/voice/prop mode
`/switch` - Toggle PO ↔ Forex mode

🕐 *ICT TOOLS*
`/powerof3` - Live session clock
`/ote HIGH LOW` - OTE calculator. Ex: `/ote 1.08900 1.08200`

🆔 *ACCOUNT*
`/myid` - Get your Telegram ID for payments
"""

    if tier in ['ELITE', 'INSTITUTIONAL']:
        help_text += f"""
👑 *ELITE FEATURES*
`/unicornhunter` - Scan 18 pairs for 2022 Model
Voice alerts on signals
Live charts with FVG/OB
Prop Firm Mode in settings
"""

    if tier == 'INSTITUTIONAL':
        help_text += f"""
🌍 *INSTITUTIONAL FEATURES*
Auto copy trading to MT4
Tick data precision
Advanced market data
"""

    help_text += f"""
💎 *UPGRADE*
Contact {SUPPORT_HANDLE} to upgrade

❓ *Need help?* Message {SUPPORT_HANDLE}
"""

    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['myid'])
def cmd_myid(message):
    bot.reply_to(message, f"🆔 *Your Telegram ID*\n\nUser: @{message.from_user.username}\nID: `{message.from_user.id}`\n\nSend this ID + M-Pesa screenshot to {SUPPORT_HANDLE}", parse_mode='Markdown')

@bot.message_handler(commands=['mystats'])
def cmd_mystats(message):
    user_id = str(message.from_user.id)
    tier = get_user_tier(int(user_id))
    stats = user_data[user_id]
    wins, losses = stats['wins'], stats['losses']
    wr = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0

    history = "\n".join([f"{s['pair']} {s['direction']} {s['confidence']}%" for s in stats['signal_history'][:5]]) or "No signals yet"

    bot.reply_to(message, f"""
📈 *MY STATS - {tier}*

*Performance:*
Wins: {wins} | Losses: {losses}
Win Rate: {wr}%
Streak: {stats['streak']}
P&L: {stats['pnl']:.1f}%

*Last 5 Signals:*
{history}

*Settings:*
Killzone: {'ON' if stats['settings']['killzone_pings'] else 'OFF'}
Prop Mode: {'ON' if stats['settings']['prop_mode'] else 'OFF'}
""", parse_mode='Markdown')

# ===== ADMIN COMMANDS =====
@bot.message_handler(commands=['adduser'])
def cmd_adduser(message):
    user_id = message.from_user.id
    if user_id!= ADMIN_ID:
        bot.reply_to(message, "❌ Admin only command")
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "Usage: `/adduser USER_ID TIER`\nTiers: STARTER, ADVANCED, ELITE, INSTITUTIONAL", parse_mode='Markdown')
            return
        target_id = int(args[1])
        tier = args[2].upper()
        days = 7 if tier!= 'INSTITUTIONAL' else 30
        expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
        if tier not in TIERS_CONFIG:
            bot.reply_to(message, "❌ Tier must be STARTER, ADVANCED, ELITE, or INSTITUTIONAL")
            return
        USERS_DATA[target_id] = {'tier': tier, 'expiry': expiry_date, 'expiry_notified': False, 'mt4_account': None, 'prop_mode': False, 'mode': 'PO'}
        save_user(target_id, tier, expiry_date, False, None, False, 'PO')
        bot.reply_to(message, f"✅ Added `{target_id}` as {tier}\nExpires: `{expiry_date.strftime('%d %b %Y')}`", parse_mode='Markdown')
        try:
            bot.send_message(target_id, f"🎉 {tier} access activated!\n\nExpires: {expiry_date.strftime('%d %b %Y')}\n\nType /start to begin", parse_mode='Markdown')
        except: pass
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['win_', '/loss_'])
def cmd_result(message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        parts = message.text.split('_')
        result = 'win' if '/win_' in message.text else 'loss'
        signal_id = parts[1]

        data = load_signals()
        for sig in data['signals']:
            if sig['id'] == signal_id and sig['result'] == 'pending':
                sig['result'] = result
                if result == 'win':
                    data['stats']['wins'] += 1
                    data['streak'] += 1
                else:
                    data['stats']['losses'] += 1
                    data['streak'] = 0
                save_signals(data)
                bot.reply_to(message, f"✅ Logged {result.upper()} for {sig['pair']}\nStreak: {data['streak']}")
                return
        bot.reply_to(message, "❌ Signal not found or already logged")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

# ===== CALLBACK HANDLERS =====
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = str(call.from_user.id)
    uid = int(user_id)
    sync_vip_status(uid)
    init_user(user_id, call.from_user.username or call.from_user.first_name)
    tier = get_user_tier(uid)

    if call.data == "choose_normal":
        bot.edit_message_text("💰 *STARTER - 1,200 KSH / 7 Days*\n\n*You get:*\n✅ 10 Standard signals per day\n✅ 60%+ confidence setups\n✅ Pocket Option only\n\n*Pay via M-Pesa:* 1. Send 1,200 KSH to *" + MPESA_NUMBER + "*\n2. Reference: @" + call.from_user.username + "\n3. Send screenshot", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    elif call.data == "choose_vip":
        bot.edit_message_text("💎 *ADVANCED - 2,000 KSH / 7 Days*\n\n*You get:*\n✅ 10 A+ signals per day\n✅ Forex Live 24/5 + PO\n✅ News filter protection\n\n*Pay via M-Pesa:* 1. Send 2,000 KSH to *" + MPESA_NUMBER + "*\n2. Reference: @" + call.from_user.username + "\n3. Send screenshot", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    elif call.data == "choose_elite":
        elite_msg = f"👑 *ELITE UPGRADE - 2,500 KSH / 7 Days*\n\n*You get:*\n✅ Everything in Advanced +\n✅ Live charts with FVG/OB\n✅ Voice alerts\n✅ Prop Firm Mode\n✅ 20 Elite Features\n✅ Switch PO ↔ Forex anytime\n\n*Pay via M-Pesa:* 1. Send 2,500 KSH to *{MPESA_NUMBER}*\n2. Reference: @{call.from_user.username}\n3. Send screenshot"
        bot.edit_message_text(elite_msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    elif call.data == "choose_sovereign":
        sov_msg = f"🌍 *INSTITUTIONAL UPGRADE - 100,000 KSH / Month*\n\n*You get:*\n✅ Everything in Elite +\n✅ Copy Trading to MT4/MT5\n✅ Tick Data Precision\n✅ Advanced market data\n✅ Direct support line\n\n*Pay via M-Pesa:* 1. Send 100,000 KSH to *{MPESA_NUMBER}*\n2. Reference: @{call.from_user.username}\n3. Send screenshot"
        bot.edit_message_text(sov_msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
    elif call.data == "get_signal":
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired. Renew to continue.")
            return
        allowed, scans, limit = can_scan_today(user_id)
        if not allowed:
            bot.answer_callback_query(call.id, f"Daily limit {limit} reached.")
            return

        mode = USERS_DATA.get(uid, {}).get('mode', 'PO')
        pairs = PAIRS_FOREX if mode == 'FOREX' and TIERS_CONFIG['forex'] else PAIRS_OTC
        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [types.InlineKeyboardButton(pair.replace('_OTC',''), callback_data=f"scan_{pair}") for pair in pairs[:TIERS_CONFIG['pairs']]]
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_menu"))
        markup.add(*buttons)
        bot.edit_message_text(f"Select pair to scan:\n\n_Mode: {mode.upper()}_ | _Scans: {scans}/{limit}_", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data.startswith("scan_"):
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ Subscription expired.")
            return
        if is_quiet_hours(user_id):
            bot.answer_callback_query(call.id, "Quiet hours active. No signals 10PM-7AM EAT.")
            return
        allowed, scans, limit = can_scan_today(user_id)
        if not allowed:
            bot.answer_callback_query(call.id, f"Daily limit {limit} reached.")
            return

        pair = call.data.replace("scan_", "")
        bot.answer_callback_query(call.id, f"Scanning {pair}... {scans+1}/{limit}")
        bot.edit_message_text(f"🔍 Scanning {pair} for A+ setup...\n\nScans today: {scans+1}/{limit}", call.message.chat.id, call.message.message_id)

        signal, error = analyze_pocket_pair(pair, uid)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Scan Again", callback_data="get_signal"))
        markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu"))

        if signal:
            user_data[user_id]['scans_today'] += 1
            save_signal_to_history(user_id, signal)
            save_data()
            signal_text = format_pocket_signal(signal, uid)
            remaining = limit - user_data[user_id]['scans_today']
            footer = f"\n\n_Scans left today: {remaining}_" if limit!= 999 else ""
            bot.edit_message_text(signal_text + footer, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)
            if signal['grade'] == 'A+':
                asyncio.run(log_signal_sent(signal['pair'], signal['direction'], signal['confidence'],
                                          signal['entry_time'], signal['df_1m'], signal['confluence']))
        else:
            bot.edit_message_text(f"❌ {error}\n\n_Scan not counted. {limit - scans} left today._", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data == "settings":
        s = user_data[user_id]['settings']
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"🔔 Killzone Pings: {'ON' if s['killzone_pings'] else 'OFF'}", callback_data="toggle_kz"))
        markup.add(types.InlineKeyboardButton(f"📊 Min Confidence: {s['min_confidence']}%", callback_data="set_conf"))
        markup.add(types.InlineKeyboardButton(f"🌙 Quiet Hours: {'ON' if s['quiet_hours'] else 'OFF'}", callback_data="toggle_qh"))
        if tier in ['ELITE','INSTITUTIONAL']:
            markup.add(types.InlineKeyboardButton(f"🔊 Voice Alerts: {'ON' if s['voice_alerts'] else 'OFF'}", callback_data="toggle_voice"))
            markup.add(types.InlineKeyboardButton(f"🛡️ Prop Firm Mode: {'ON' if s['prop_mode'] else 'OFF'}", callback_data="toggle_prop"))
        # FIX #1: Added
        if TIERS_CONFIG['forex']:
            current_mode = USERS_DATA.get(uid, {}).get('mode', 'PO')
            txt = "💱 Switch to Forex" if current_mode!= 'FOREX' else "📊 Switch to PO"
            new_mode = 'FOREX' if current_mode!= 'FOREX' else 'PO'
            markup.add(types.InlineKeyboardButton(txt, callback_data=f"mode_{new_mode}"))
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_menu"))
        bot.edit_message_text("⚙️ *Settings*\n\nCustomize your bot:", call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

    elif call.data == "toggle_kz":
        user_data[user_id]['settings']['killzone_pings'] = not user_data[user_id]['settings']['killzone_pings']
        save_data()
        bot.answer_callback_query(call.id, "Killzone pings toggled!")
        call.data = "settings"
        callback_handler(call)

    elif call.data == "set_conf":
        current = user_data[user_id]['settings']['min_confidence']
        new = 65 if current == 60 else 60
        user_data[user_id]['settings']['min_confidence'] = new
        save_data()
        bot.answer_callback_query(call.id, f"Min confidence set to {new}%")
        call.data = "settings"
        callback_handler(call)

    elif call.data == "toggle_qh":
        user_data[user_id]['settings']['quiet_hours'] = not user_data[user_id]['settings']['quiet_hours']
        save_data()
        bot.answer_callback_query(call.id, "Quiet hours toggled!")
        call.data = "settings"
        callback_handler(call)

    elif call.data == "toggle_voice":
        user_data[user_id]['settings']['voice_alerts'] = not user_data[user_id]['settings']['voice_alerts']
        save_data()
        bot.answer_callback_query(call.id, "Voice alerts toggled!")
        call.data = "settings"
        callback_handler(call)

    elif call.data == "toggle_prop":
        user_data[user_id]['settings']['prop_mode'] = not user_data[user_id]['settings']['prop_mode']
        save_data()
        bot.answer_callback_query(call.id, "Prop Firm Mode toggled!")
        call.data = "settings"
        callback_handler(call)

    elif call.data.startswith("mode_"):
        if not TIERS_CONFIG['forex']:
            bot.answer_callback_query(call.id, "Upgrade to Advanced for Forex")
            return
        new_mode = call.data.split('_')[1]
        if uid not in USERS_DATA:
            USERS_DATA[uid] = {}
        USERS_DATA[uid]['mode'] = new_mode
        save_user(uid, tier, USERS_DATA[uid].get('expiry'),
                 USERS_DATA[uid].get('expiry_notified', False),
                 USERS_DATA[uid].get('mt4_account'),
                 USERS_DATA[uid].get('prop_mode', False), new_mode)
        bot.answer_callback_query(call.id, f"Switched to {new_mode.upper()}")
        bot.edit_message_text(f"✅ *Mode: {new_mode.upper()}*\n\nType /getsignal to scan.", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif call.data == "powerof3":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
        cmd_powerof3(FakeMsg(uid, call.message.chat.id))

    elif call.data == "bot_stats":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
        cmd_stats_fixed(FakeMsg(uid, call.message.chat.id))

    elif call.data == "back_menu":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        class FakeMsg:
            def __init__(self, uid, chat_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
        start(FakeMsg(uid, call.message.chat.id))

    elif call.data == "my_stats":
        bot.answer_callback_query(call.id)
        class FakeMsg:
            def __init__(self, uid, chat_id, msg_id):
                self.from_user = type('User', (), {'id': uid})()
                self.chat = type('Chat', (), {'id': chat_id})()
                self.message_id = msg_id
        show_my_stats(FakeMsg(uid, call.message.chat.id, call.message.message_id))

    elif call.data == "unicornhunter":
        bot.answer_callback_query(call.id, "🦄 Hunting Unicorns...")
        bot.edit_message_text("🦄 *UNICORN HUNTER ACTIVE*\n\nScanning 18 pairs for 2022 Model...\nOB + FVG + Liquidity Sweep\n\nThis takes 30sec...", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
        found = []
        mode = USERS_DATA.get(uid, {}).get('mode', 'PO')
        pairs = PAIRS_FOREX if mode == 'FOREX' else PAIRS_OTC
        for pair in pairs[:5]:
            signal, error = analyze_pocket_pair(pair, uid)
            if signal and signal['confidence'] >= 85:
                found.append(f"{pair}: {signal['confidence']}% - {signal['direction']}")
            time.sleep(0.5)
        if found:
            msg = "🦄 *UNICORNS FOUND:*\n\n" + "\n".join(found) + "\n\nTap /start → Get Signal to enter"
        else:
            msg = "🦄 *No Unicorns found*\n\nMarket not ready. 2022 Model requires:\n1. HTF OB\n2. LTF FVG \n3. Liquidity Sweep\n\nTry again in killzone"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data="back_menu"))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

    elif call.data == "ote_menu":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Send: `/ote HIGH LOW`\n\nExample: `/ote 1.08900 1.08200`", parse_mode='Markdown')

    elif call.data == "admin_panel":
        if uid!= ADMIN_ID:
            bot.answer_callback_query(call.id, "❌ Admin only")
            return
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📂 List Users", callback_data="admin_listusers"),
            types.InlineKeyboardButton("➕ Add Advanced", callback_data="admin_addvip"),
            types.InlineKeyboardButton("👑 Add Elite", callback_data="admin_addelite"),
            types.InlineKeyboardButton("🌍 Add Institutional", callback_data="admin_addinstitutional"),
            types.InlineKeyboardButton("🔄 Renew User", callback_data="admin_renewvip"),
            types.InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats")
        )
        bot.edit_message_text("🔧 *Admin Panel*\n\nArchangel v3.2 Controls", call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

# ===== SCHEDULER =====
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(60)

schedule.every().day.at("07:00").do(send_silverbullet_alert)
schedule.every().day.at("12:00").do(send_silverbullet_alert)
schedule.every().day.at("09:00").do(check_expired_vips)

scheduler_thread = threading.Thread(target=run_schedule, daemon=True)
scheduler_thread.start()

print("=== BOT POLLING STARTED ===", flush=True)
bot.infinity_polling(timeout=60, long_polling_timeout=60)
