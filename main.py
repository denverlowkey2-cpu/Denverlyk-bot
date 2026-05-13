import telebot
from telebot import types
from datetime import datetime, timedelta, timezone
import threading
import time
import requests
import os
import json

# ======== CONFIG ========
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER')
CHANNEL_ID = os.getenv('CHANNEL_ID', '')
CHANNEL_ID = int(CHANNEL_ID) if CHANNEL_ID else None
TWELVEDATA_API_KEY = os.getenv('TWELVEDATA_API_KEY')
SUPPORT_HANDLE = os.getenv('SUPPORT_HANDLE')

# 12Data rate limit protection
TWELVEDATA_CALLS = 0
TWELVEDATA_RESET = datetime.now(timezone.utc)
CALL_DELAY = 8 # 8s = 7-8 calls/min, safe for free plan

# Pricing per tier - weekly
PRICING = {
    'elite': 1500,
    'lite': 700,
    'booster': 500
}

CRYPTO_PAIRS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'DOGE', 'AVAX', 'MATIC', 'DOT']
FOREX_PAIRS = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/USD', 'USD/CAD']
GOLD_PAIRS = ['XAU/USD']
INDEX_PAIRS = ['US30', 'US100', 'NAS100']

ALL_PAIRS = {
    'crypto': CRYPTO_PAIRS,
    'forex': FOREX_PAIRS,
    'gold': GOLD_PAIRS,
    'indices': INDEX_PAIRS
}

SCAN_INTERVAL = 60
MIN_CONFLUENCE = 5
MIN_CONFLUENCE_POCKET = 6
MIN_CONFLUENCE_BOOSTER = 4
MAX_SIGNALS_PER_DAY = 30
BINANCE_SYMBOLS = [f'{p}USDT' for p in CRYPTO_PAIRS]

bot = telebot.TeleBot(TOKEN)
DEFAULT_ACCOUNT_BALANCE = 1000
REF_BONUS_DAYS = 2
DATA_FILE = 'bot_data.json'

# ========= DATABASES =========
subscribers = {}
SUB_EXPIRY = {}
REFERRALS = {}
PENDING_CREDIT = {}
REF_MAP = {}
LAST_SIGNAL = {}
POCKET_USERS = set()
POCKET_LITE_USERS = set()
BOOSTER_USERS = set()
USER_SETTINGS = {}
SIGNALS_SENT_24H = {}
LAST_HEARTBEAT = {}
USER_TIER = {}

# ========= PERSISTENCE =========
def save_data():
    data = {
        'subscribers': subscribers,
        'SUB_EXPIRY': {str(k): v.isoformat() for k, v in SUB_EXPIRY.items()},
        'REFERRALS': REFERRALS,
        'PENDING_CREDIT': PENDING_CREDIT,
        'REF_MAP': REF_MAP,
        'POCKET_USERS': list(POCKET_USERS),
        'POCKET_LITE_USERS': list(POCKET_LITE_USERS),
        'BOOSTER_USERS': list(BOOSTER_USERS),
        'USER_SETTINGS': USER_SETTINGS,
        'USER_TIER': USER_TIER,
        'SIGNALS_SENT_24H': SIGNALS_SENT_24H
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

def load_data():
    global subscribers, SUB_EXPIRY, REFERRALS, PENDING_CREDIT, REF_MAP, POCKET_USERS, POCKET_LITE_USERS, BOOSTER_USERS, USER_SETTINGS, USER_TIER, SIGNALS_SENT_24H
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            subscribers = data.get('subscribers', {})
            SUB_EXPIRY = {int(k): datetime.fromisoformat(v) for k, v in data.get('SUB_EXPIRY', {}).items()}
            REFERRALS = data.get('REFERRALS', {})
            PENDING_CREDIT = data.get('PENDING_CREDIT', {})
            REF_MAP = data.get('REF_MAP', {})
            POCKET_USERS = set(data.get('POCKET_USERS', []))
            POCKET_LITE_USERS = set(data.get('POCKET_LITE_USERS', []))
            BOOSTER_USERS = set(data.get('BOOSTER_USERS', []))
            USER_SETTINGS = data.get('USER_SETTINGS', {})
            USER_TIER = data.get('USER_TIER', {})
            SIGNALS_SENT_24H = data.get('SIGNALS_SENT_24H', {})
    except:
        pass

def get_user_settings(uid):
    if uid not in USER_SETTINGS:
        USER_SETTINGS[uid] = {
            'assets': {'crypto': True, 'forex': True, 'gold': True, 'indices': True},
            'pairs': BINANCE_SYMBOLS[:3] + FOREX_PAIRS[:2] # default 5 pairs
        }
    return USER_SETTINGS[uid]

def get_user_tier(uid):
    return USER_TIER.get(uid, 'lite')

def get_user_mode(uid):
    if uid in POCKET_USERS:
        return "ELITE 6/6", MIN_CONFLUENCE_POCKET, 'elite'
    if uid in POCKET_LITE_USERS:
        return "LITE 5/6", MIN_CONFLUENCE, 'lite'
    if uid in BOOSTER_USERS:
        return "BOOSTER 4/6", MIN_CONFLUENCE_BOOSTER, 'booster'
    tier = get_user_tier(uid)
    if tier == 'elite': return "ELITE 6/6", MIN_CONFLUENCE_POCKET, 'elite'
    if tier == 'booster': return "BOOSTER 4/6", MIN_CONFLUENCE_BOOSTER, 'booster'
    return "LITE 5/6", MIN_CONFLUENCE, 'lite'

# ========= 12DATA RATE LIMITING =========
def get_twelvedata_klines(symbol, interval='1h', limit=200):
    global TWELVEDATA_CALLS, TWELVEDATA_RESET

    if not TWELVEDATA_API_KEY:
        return None

    now = datetime.now(timezone.utc)
    if (now - TWELVEDATA_RESET).seconds >= 60:
        TWELVEDATA_CALLS = 0
        TWELVEDATA_RESET = now

    if TWELVEDATA_CALLS >= 7:
        wait_time = 60 - (now - TWELVEDATA_RESET).seconds
        if wait_time > 0:
            time.sleep(wait_time)
        TWELVEDATA_CALLS = 0
        TWELVEDATA_RESET = datetime.now(timezone.utc)

    time.sleep(CALL_DELAY)

    td_interval = interval.replace('m', 'min').replace('d', 'day')
    url = f'https://api.twelvedata.com/time_series?symbol={symbol}&interval={td_interval}&outputsize={limit}&apikey={TWELVEDATA_API_KEY}'
    data = safe_request(url)

    TWELVEDATA_CALLS += 1

    if not data or 'values' not in data or data.get('status') == 'error':
        return None

    klines = []
    try:
        for v in reversed(data['values']):
            klines.append([
                int(datetime.strptime(v['datetime'], '%Y-%m-%d %H:%M:%S').timestamp() * 1000),
                v['open'], v['high'], v['low'], v['close'], v.get('volume', '0')
            ])
    except:
        return None
    return klines

def safe_request(url, timeout=8):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        print(f"REQUEST FAIL: {str(e)[:50]}", flush=True)
        return None

def get_binance_klines(symbol, interval='1h', limit=200):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    return safe_request(url)

def get_klines(symbol, interval='1h', limit=200):
    if '/' in symbol or symbol in ['US30', 'XAU/USD']:
        return get_twelvedata_klines(symbol, interval, limit)
    else:
        return get_binance_klines(symbol, interval, limit)

# ========= TECHNICAL ANALYSIS =========
def ema(data, period):
    if len(data) < period: return [data[-1]] * len(data)
    k = 2 / (period + 1)
    ema_vals = [data[0]]
    for price in data[1:]:
        ema_vals.append(price * k + ema_vals[-1] * (1 - k))
    return ema_vals

def calculate_indicators(klines):
    try:
        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        if len(closes) < 50: return None

        ema21 = ema(closes, 21)
        ema50 = ema(closes, 50)
        ema200 = ema(closes, 200)
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        macd = [a - b for a, b in zip(ema12, ema26)]
        signal = ema(macd, 9)

        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
        avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 0.0001
        rs = avg_gain / avg_loss if avg_loss!= 0 else 100
        rsi = 100 - (100 / (1 + rs))

        typical_price = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        vol_slice = volumes[-20:]
        vwap = sum([tp * v for tp, v in zip(typical_price[-20:], vol_slice)]) / sum(vol_slice) if sum(vol_slice) > 0 else closes[-1]
        avg_vol = sum(vol_slice) / 20 if sum(vol_slice) > 0 else 1
        vol_spike = volumes[-1] > avg_vol * 1.3

        return {
            'close': closes[-1], 'low': lows[-1], 'high': highs[-1],
            'ema21': ema21[-1], 'ema50': ema50[-1], 'ema200': ema200[-1],
            'macd': macd[-1], 'signal': signal[-1], 'rsi': rsi,
            'vwap': vwap, 'vol_spike': vol_spike
        }
    except:
        return None

def check_all_strategies(symbol, min_conf=MIN_CONFLUENCE):
    tf30m = get_klines(symbol, '30m', 200)
    tf4h = get_klines(symbol, '4h', 200)
    tf1d = get_klines(symbol, '1d', 200)
    if not tf30m or not tf4h or not tf1d: return []

    i30m = calculate_indicators(tf30m)
    i4h = calculate_indicators(tf4h)
    i1d = calculate_indicators(tf1d)
    if not i30m or not i4h or not i1d: return []

    price = i30m['close']
    strategies = []

    def confluence_count(conditions):
        return sum(1 for c in conditions if c)

    triple_bull = i30m['ema21'] > i30m['ema50'] and i4h['ema21'] > i4h['ema50'] and i1d['ema21'] > i1d['ema50']
    triple_bear = i30m['ema21'] < i30m['ema50'] and i4h['ema21'] < i4h['ema50'] and i1d['ema21'] < i1d['ema50']
    bias_long = i1d['close'] > i1d['ema200'] and i30m['close'] > i30m['vwap']
    bias_short = i1d['close'] < i1d['ema200'] and i30m['close'] < i30m['vwap']
    macd_long = i30m['macd'] > i30m['signal']
    macd_short = i30m['macd'] < i30m['signal']
    vwap_long = i30m['low'] <= i30m['vwap'] * 1.008 and i30m['close'] > i30m['ema21']
    vwap_short = i30m['high'] >= i30m['vwap'] * 0.992 and i30m['close'] < i30m['ema21']
    rsi_long = i30m['rsi'] < 35 and i1d['ema21'] > i1d['ema50']
    rsi_short = i30m['rsi'] > 65 and i1d['ema21'] < i1d['ema50']
    vol_long = i30m['vol_spike'] and i30m['macd'] > i30m['signal']
    vol_short = i30m['vol_spike'] and i30m['macd'] < i30m['signal']

    conditions_long = [triple_bull, bias_long, macd_long, vwap_long, rsi_long, vol_long]
    if confluence_count(conditions_long) >= min_conf:
        if '/' in symbol or 'US30' in symbol or 'XAU' in symbol:
            sl = price * 0.998; tp1 = price * 1.004; tp2 = price * 1.008
        else:
            sl = price*0.988; tp1 = price*1.02; tp2 = price*1.04
        strategies.append({'name': 'Denverlyk SUPER', 'dir': 'LONG', 'action': 'BUY',
            'sl': sl, 'tp1': tp1, 'tp2': tp2, 'confluence': confluence_count(conditions_long), 'price': price, 'symbol': symbol})

    conditions_short = [triple_bear, bias_short, macd_short, vwap_short, rsi_short, vol_short]
    if confluence_count(conditions_short) >= min_conf:
        if '/' in symbol or 'US30' in symbol or 'XAU' in symbol:
            sl = price * 1.002; tp1 = price * 0.996; tp2 = price * 0.992
        else:
            sl = price*1.012; tp1 = price*0.98; tp2 = price*0.96
        strategies.append({'name': 'Denverlyk SUPER', 'dir': 'SHORT', 'action': 'SELL',
            'sl': sl, 'tp1': tp1, 'tp2': tp2, 'confluence': confluence_count(conditions_short), 'price': price, 'symbol': symbol})

    return strategies

def get_asset_type(symbol):
    if 'USDT' in symbol: return 'crypto'
    if symbol in ['XAU/USD']: return 'gold'
    if symbol in ['US30', 'US100', 'NAS100']: return 'indices'
    if '/' in symbol: return 'forex'
    return 'crypto'

# ========= MT4 HELPER =========
MT4_SYMBOL_MAP = {
    'BTCUSDT': 'BTCUSD', 'ETHUSDT': 'ETHUSD', 'SOLUSDT': 'SOLUSD',
    'BNBUSDT': 'BNBUSD', 'XRPUSDT': 'XRPUSD', 'ADAUSDT': 'ADAUSD', 'DOGEUSDT': 'DOGEUSD',
    'EUR/USD': 'EURUSD', 'GBP/USD': 'GBPUSD', 'USD/JPY': 'USDJPY',
    'XAU/USD': 'XAUUSD', 'US30': 'US30'
}

def calculate_lot_size(entry, sl, account_balance=1000, risk_pct=1, symbol="EURUSD"):
    try:
        risk_amount = account_balance * (risk_pct / 100)
        pip_diff = abs(float(entry) - float(sl))
        symbol = symbol.upper()

        if 'XAU' in symbol or 'GOLD' in symbol:
            pips = pip_diff / 0.01
            lot_size = risk_amount / (pips * 1.0 * 100) if pips!= 0 else 0.01
        elif 'JPY' in symbol:
            pips = pip_diff * 100
            lot_size = risk_amount / (pips * 10.0) if pips!= 0 else 0.01
        else:
            pips = pip_diff * 10000
            lot_size = risk_amount / (pips * 10.0) if pips!= 0 else 0.01

        return max(0.01, round(lot_size, 2))
    except:
        return 0.01

def format_mt4_signal(result, account_balance=1000):
    mt4_symbol = MT4_SYMBOL_MAP.get(result['symbol'], result['symbol'].replace('USDT','USD').replace('/',''))
    order_type = "Sell Limit" if result['dir'] == 'SHORT' else "Buy Limit"
    lot_size = calculate_lot_size(result['price'], result['sl'], account_balance, 1, mt4_symbol)
    risk = abs(result['price'] - result['sl'])
    reward1 = abs(result['tp1'] - result['price'])
    rr1 = round(reward1 / risk, 1) if risk!= 0 else 0

    return f"""**MT4 SETUP** 📊
**Symbol:** {mt4_symbol}
**Order:** {order_type}
**Entry:** {result['price']:.5f}
**SL:** {result['sl']:.5f}
**TP1:** {result['tp1']:.5f} | R:R 1:{rr1}
**TP2:** {result['tp2']:.5f}
**Lot Size:** {lot_size} lots = 1% risk
**Account:** ${account_balance}
**Confluence:** {result['confluence']}/6"""

# ========= COMMANDS =========
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    if len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith('ref_'):
            referrer_id = int(param.replace('ref_', ''))
            if referrer_id!= uid and uid not in REF_MAP:
                REF_MAP[uid] = referrer_id
                if referrer_id not in REFERRALS: REFERRALS[referrer_id] = []
                if uid not in REFERRALS[referrer_id]: REFERRALS[referrer_id].append(uid)
                save_data()

    if uid == ADMIN_ID:
        bot.reply_to(message, f"**Welcome Owner** 👑\n\nV3.1 SUPER ELITE Online\nUse /menu", parse_mode='Markdown')
    else:
        if uid not in subscribers or not subscribers.get(uid):
            bot.reply_to(message, f"""**Denverlyk SUPER ELITE** 🔥

**A-Grade Signals 24/7**
Choose your pairs to save API calls

**Pricing:**
👑 ELITE 6/6: Ksh {PRICING['elite']}/week | 1-4 signals/week
💎 LITE 5/6: Ksh {PRICING['lite']}/week | 5-15 signals/week
⚡ BOOSTER 4/6: Ksh {PRICING['booster']}/week | 15-30 signals/week

**1. Subscribe**
Send payment to: **{MPESA_NUMBER}**

**2. Confirm**
Tap /confirm after payment

**Referrals:** +{REF_BONUS_DAYS} days per referral
**5 referrals:** 1 week free

*Questions? Tap /help*""", parse_mode='Markdown')
        else:
            menu(message)

@bot.message_handler(commands=['menu'])
def menu(message):
    _menu(message.chat.id, message.from_user.id)

def _menu(chat_id, uid):
    if uid!= ADMIN_ID and (uid not in subscribers or not subscribers.get(uid)):
        bot.send_message(chat_id, f"🔒 **Subscribe First**\n\nSend payment to {MPESA_NUMBER}\nThen tap /confirm", parse_mode='Markdown')
        return

    settings = get_user_settings(uid)
    mode_name, _, tier = get_user_mode(uid)
    pocket_elite = "🟢 ON" if uid in POCKET_USERS else "🔴 OFF"
    pocket_lite = "🟢 ON" if uid in POCKET_LITE_USERS else "🔴 OFF"
    booster = "🟢 ON" if uid in BOOSTER_USERS else "🔴 OFF"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📲 Get Signal Now", callback_data='signal_now'),
        types.InlineKeyboardButton("🎯 Select Pairs", callback_data='select_pairs'),
        types.InlineKeyboardButton("🆔 Get My ID", callback_data='getid'),
        types.InlineKeyboardButton("⚙️ Asset Filters", callback_data='assets'),
        types.InlineKeyboardButton(f"👑 ELITE {pocket_elite}", callback_data='pocket_elite'),
        types.InlineKeyboardButton(f"💎 LITE {pocket_lite}", callback_data='pocket_lite'),
        types.InlineKeyboardButton(f"⚡ BOOSTER {booster}", callback_data='booster'),
        types.InlineKeyboardButton("📊 MT4 Lot Calc", callback_data='mt4'),
        types.InlineKeyboardButton("📈 My Stats", callback_data='stats'),
        types.InlineKeyboardButton("💬 Support", url=f'https://t.me/{SUPPORT_HANDLE}')
    )

    bot.send_message(
        chat_id,
        f"""**DENVERLYK SUPER ELITE** 🔥

**Status:** Active ✅
**Mode:** {mode_name}
**Pairs Selected:** {len(settings['pairs'])}
**Your ID:** `{uid}`

*Select only pairs you trade to save API calls and get faster signals*""",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: True)
def button_handler(call):
    user_id = call.from_user.id
    settings = get_user_settings(user_id)

    if call.data == 'signal_now':
        bot.answer_callback_query(call.id, "Scanning...")
        manual_signal(call.message)

    elif call.data == 'select_pairs':
        show_pair_selection(call.message, user_id)

    elif call.data == 'getid':
        bot.answer_callback_query(call.id, f"Your ID: {user_id}")
        bot.send_message(call.message.chat.id, f"**Your Telegram ID:** `{user_id}`\n\nCopy this for support/admin.", parse_mode='Markdown')

    elif call.data == 'assets':
        show_asset_filters(call.message, user_id)

    elif call.data.startswith('toggle_asset_'):
        asset = call.data.replace('toggle_asset_', '')
        settings['assets'][asset] = not settings['assets'][asset]
        save_data()
        bot.answer_callback_query(call.id, f"{asset.upper()} {'ON' if settings['assets'][asset] else 'OFF'}")
        show_asset_filters(call.message, user_id)

    elif call.data.startswith('toggle_pair_'):
        pair = call.data.replace('toggle_pair_', '')
        if pair in settings['pairs']:
            settings['pairs'].remove(pair)
        else:
            if len(settings['pairs']) >= 10:
                bot.answer_callback_query(call.id, "Max 10 pairs. Remove one first.", show_alert=True)
                return
            settings['pairs'].append(pair)
        save_data()
        bot.answer_callback_query(call.id, f"{pair} {'ON' if pair in settings['pairs'] else 'OFF'}")
        show_pair_selection(call.message, user_id)

    elif call.data == 'pocket_elite':
        toggle_mode(user_id, 'elite', call.message, call.id)
    elif call.data == 'pocket_lite':
        toggle_mode(user_id, 'lite', call.message, call.id)
    elif call.data == 'booster':
        toggle_mode(user_id, 'booster', call.message, call.id)

    elif call.data == 'mt4':
        bot.answer_callback_query(call.id)
        msg = """**MT4 Lot Size Calculator** 📊
Send: `/mt4 1000` for $1000 account
*Bot auto-calculates 1% risk per trade*"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("◀️ Back", callback_data='menu'))
        bot.edit_message_text(msg, call.message.chat.id, call.message_id, reply_markup=markup, parse_mode='Markdown')

    elif call.data == 'stats':
        expiry = SUB_EXPIRY.get(user_id)
        expiry_text = expiry.strftime('%d %b %Y') if expiry else "Lifetime"
        mode_name, _, tier = get_user_mode(user_id)
        signals_24h = SIGNALS_SENT_24H.get(user_id, 0)
        refs = len(REFERRALS.get(user_id, []))
        bot.answer_callback_query(call.id)
        msg = f"""**Your Stats** 📈
**Account:** Active ✅
**Tier:** {tier.upper()}
**Mode:** {mode_name}
**Expires:** {expiry_text}
**Pairs:** {len(settings['pairs'])}
**Signals 24h:** {signals_24h}
**Referrals:** {refs}"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("◀️ Back", callback_data='menu'))
        bot.edit_message_text(msg, call.message.chat.id, call.message_id, reply_markup=markup, parse_mode='Markdown')

    elif call.data == 'menu':
        bot.answer_callback_query(call.id)
        bot.delete_message(call.message.chat.id, call.message_id)
        _menu(call.message.chat.id, user_id)

def toggle_mode(user_id, mode, message, call_id):
    if user_id!= ADMIN_ID and (user_id not in subscribers or not subscribers.get(user_id)):
        bot.answer_callback_query(call_id, "Subscribe first!", show_alert=True)
        return

    if mode == 'elite':
        if user_id in POCKET_USERS:
            POCKET_USERS.remove(user_id)
            bot.answer_callback_query(call_id, "ELITE Mode OFF")
        else:
            POCKET_USERS.add(user_id)
            POCKET_LITE_USERS.discard(user_id)
            BOOSTER_USERS.discard(user_id)
            USER_TIER[user_id] = 'elite'
            bot.answer_callback_query(call_id, "ELITE Mode ON")
    elif mode == 'lite':
        if user_id in POCKET_LITE_USERS:
            POCKET_LITE_USERS.remove(user_id)
            bot.answer_callback_query(call_id, "LITE Mode OFF")
        else:
            POCKET_LITE_USERS.add(user_id)
            POCKET_USERS.discard(user_id)
            BOOSTER_USERS.discard(user_id)
            USER_TIER[user_id] = 'lite'
            bot.answer_callback_query(call_id, "LITE Mode ON")
    elif mode == 'booster':
        if user_id in BOOSTER_USERS:
            BOOSTER_USERS.remove(user_id)
            bot.answer_callback_query(call_id, "BOOSTER Mode OFF")
        else:
            BOOSTER_USERS.add(user_id)
            POCKET_USERS.discard(user_id)
            POCKET_LITE_USERS.discard(user_id)
            USER_TIER[user_id] = 'booster'
            bot.answer_callback_query(call_id, "BOOSTER Mode ON")

    save_data()
    bot.delete_message(message.chat.id, message.message_id)
    _menu(message.chat.id, user_id)

def show_asset_filters(message, user_id):
    settings = get_user_settings(user_id)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{'🟢' if settings['assets']['crypto'] else '🔴'} Crypto", callback_data='toggle_asset_crypto'),
        types.InlineKeyboardButton(f"{'🟢' if settings['assets']['forex'] else '🔴'} Forex", callback_data='toggle_asset_forex'),
        types.InlineKeyboardButton(f"{'🟢' if settings['assets']['gold'] else '🔴'} Gold", callback_data='toggle_asset_gold'),
        types.InlineKeyboardButton(f"{'🟢' if settings['assets']['indices'] else '🔴'} Indices", callback_data='toggle_asset_indices'),
        types.InlineKeyboardButton("🎯 Select Pairs", callback_data='select_pairs'),
        types.InlineKeyboardButton("◀️ Back", callback_data='menu')
    )
    bot.edit_message_text("**Asset Categories** ⚙️\n\nTurn OFF categories you don't trade:", message.chat.id, message.message_id, reply_markup=markup, parse_mode='Markdown')

def show_pair_selection(message, user_id):
    settings = get_user_settings(user_id)
    markup = types.InlineKeyboardMarkup(row_width=2)

    # Show pairs from enabled assets only
    pairs_to_show = []
    if settings['assets']['crypto']:
        pairs_to_show.extend(BINANCE_SYMBOLS[:5])
    if settings['assets']['forex']:
        pairs_to_show.extend(FOREX_PAIRS)
    if settings['assets']['gold']:
        pairs_to_show.extend(GOLD_PAIRS)
    if settings['assets']['indices']:
        pairs_to_show.extend(INDEX_PAIRS)

    for pair in pairs_to_show:
        status = "✅" if pair in settings['pairs'] else "❌"
        markup.add(types.InlineKeyboardButton(f"{status} {pair}", callback_data=f'toggle_pair_{pair}'))

    markup.add(types.InlineKeyboardButton("◀️ Back", callback_data='menu'))
    bot.edit_message_text(f"**Select Pairs** 🎯\n\nSelected: {len(settings['pairs'])}/10\nTap to toggle ON/OFF. Max 10 pairs.",
                         message.chat.id, message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['getid'])
def getid_cmd(message):
    bot.reply_to(message, f"**Your Telegram ID:** `{message.from_user.id}`", parse_mode='Markdown')

@bot.message_handler(commands=['signal'])
def manual_signal(message):
    uid = message.from_user.id
    if uid!= ADMIN_ID:
        if uid not in subscribers or not subscribers.get(uid):
            bot.reply_to(message, f"🔒 Subscribers only. Pay Ksh {PRICING['lite']}")
            return

    settings = get_user_settings(uid)
    pairs_to_scan = settings['pairs']

    if not pairs_to_scan:
        bot.reply_to(message, "❌ No pairs selected. Go to /menu → Select Pairs")
        return

    mode_name, min_conf, tier = get_user_mode(uid)
    bot.reply_to(message, f"🔍 Scanning {len(pairs_to_scan)} pairs | Mode: {mode_name}...")
    signals_found = 0

    for symbol in pairs_to_scan:
        if signals_found >= 3: break
        results = check_all_strategies(symbol, min_conf=min_conf)
        for result in results:
            if result['confluence'] < min_conf: continue
            signals_found += 1
            SIGNALS_SENT_24H[uid] = SIGNALS_SENT_24H.get(uid, 0) + 1
            mt4_msg = format_mt4_signal(result, DEFAULT_ACCOUNT_BALANCE)
            send_signal_to_user(uid, result, mt4_msg, mode_name, min_conf)
            if signals_found >= 3: break

    if signals_found == 0:
        bot.send_message(message.chat.id, f"❌ No {mode_name} setups in your selected pairs right now.\n\n*Try adding more pairs in /menu → Select Pairs*")

def send_signal_to_user(uid, result, mt4_msg, mode_name, min_conf):
    asset_name = result['symbol'].replace('USDT','').replace('/','')
    emoji = "🟢" if result['dir'] == 'LONG' else "🔴"
    grade = "A-GRADE" if min_conf >= 5 else "B-GRADE"
    header = "👑 DENVERLYK ELITE 6/6" if min_conf == 6 else f"DENVERLYK SUPER {mode_name}"

    msg = f"""**{header}** 🔥

{emoji} **{asset_name} {result['dir']}** | {grade}
**Action:** {result['action']}
**Confluence:** {result['confluence']}/6

**Entry:** {result['price']:.5f}
**SL:** {result['sl']:.5f}
**TP1:** {result['tp1']:.5f}
**TP2:** {result['tp2']:.5f}

{mt4_msg}

*Risk 1% max. No revenge trades.*"""

    try:
        bot.send_message(uid, msg, parse_mode='Markdown')
    except Exception as e:
        print(f"Failed to send to {uid}: {e}", flush=True)

def send_signal_to_channel(result, mt4_msg, mode_name, min_conf):
    if not CHANNEL_ID:
        return
    asset_name = result['symbol'].replace('USDT','').replace('/','')
    emoji = "🟢" if result['dir'] == 'LONG' else "🔴"
    grade = "A-GRADE" if min_conf >= 5 else "B-GRADE"
    header = "👑 DENVERLYK ELITE 6/6" if min_conf == 6 else f"DENVERLYK SUPER {mode_name}"

    msg = f"""**{header}** 🔥

{emoji} **{asset_name} {result['dir']}** | {grade}
**Confluence:** {result['confluence']}/6

**Entry:** {result['price']:.5f}
**SL:** {result['sl']:.5f}
**TP1:** {result['tp1']:.5f}
**TP2:** {result['tp2']:.5f}

*Join @YourBotUsername for full MT4 setup*"""

    try:
        bot.send_message(CHANNEL_ID, msg, parse_mode='Markdown')
    except Exception as e:
        print(f"Failed to send to channel: {e}", flush=True)

@bot.message_handler(commands=['confirm'])
def confirm(message):
    uid = message.from_user.id
    if uid == ADMIN_ID:
        bot.reply_to(message, "Unlimited access, sir.")
        return
    bot.reply_to(message, "Send M-Pesa confirmation screenshot here. Admin activates in 5min.")
    bot.send_message(ADMIN_ID, f"⚠️ **Payment Claim**\n\nUser: @{message.from_user.username} ({uid})\n\nReply: /activate {uid} elite\nReply: /activate {uid} lite\nReply: /activate {uid} booster")

@bot.message_handler(commands=['activate'])
def activate(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        tier = parts[2].lower() if len(parts) > 2 else 'lite'

        if tier not in ['elite', 'lite', 'booster']:
            tier = 'lite'

        days = 7

        subscribers[user_id] = True
        SUB_EXPIRY[user_id] = datetime.now(timezone.utc) + timedelta(days=days)
        USER_TIER[user_id] = tier

        if tier == 'elite':
            POCKET_USERS.add(user_id)
        elif tier == 'booster':
            BOOSTER_USERS.add(user_id)
        else:
            POCKET_LITE_USERS.add(user_id)

        save_data()

        if user_id in REF_MAP:
            referrer = REF_MAP[user_id]
            PENDING_CREDIT[referrer] = PENDING_CREDIT.get(referrer, 0) + REF_BONUS_DAYS
            if referrer in SUB_EXPIRY:
                SUB_EXPIRY[referrer] += timedelta(days=REF_BONUS_DAYS)
            else:
                SUB_EXPIRY[referrer] = datetime.now(timezone.utc) + timedelta(days=REF_BONUS_DAYS)
                subscribers[referrer] = True
            bot.send_message(referrer, f"🎉 **Referral Bonus!**\n\n+{REF_BONUS_DAYS} days added.\nNew expiry: {SUB_EXPIRY[referrer].strftime('%d %b %Y')}")
            save_data()

        bot.send_message(user_id, f"""✅ **Payment Confirmed!**

**Tier:** {tier.upper()}
**Expires:** {SUB_EXPIRY[user_id].strftime('%d %b %Y')}

Tap /menu to start""", parse_mode='Markdown')
        bot.reply_to(message, f"Activated {user_id} on {tier.upper()} for 7 days.")
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)[:100]}")

@bot.message_handler(commands=['referral'])
def referral(message):
    uid = message.from_user.id
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
    earned_days = PENDING_CREDIT.get(uid, 0)
    total_refs = len(REFERRALS.get(uid, []))
    free_week = "✅ Unlocked!" if total_refs >= 5 else f"{5 - total_refs} more needed"

    bot.reply_to(message, f"""**Your Referral Link:** 🔗
`{ref_link}`

**Rewards:** +{REF_BONUS_DAYS} days per paid referral
**Earned:** {earned_days} days
**Total Referrals:** {total_refs}
**Free Week:** {free_week}

*Share it. Get paid in time* 👊""", parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_cmd(message):
    help_text = f"""**DENVERLYK SUPER ELITE HELP** 🆘

**Trading Commands:**
/menu - Main dashboard
/signal - Force scan now
/mt4 1000 - MT4 lot calc for $1000
/getid - Get your Telegram ID

**Signal Tiers:**
👑 ELITE 6/6 - Ksh {PRICING['elite']}/week | 1-4/week | A-grade
💎 LITE 5/6 - Ksh {PRICING['lite']}/week | 5-15/week | B-grade
⚡ BOOSTER 4/6 - Ksh {PRICING['booster']}/week | 15-30/week | C-grade

**Account:**
/referral - Invite friends, earn days
/confirm - Submit payment proof

**Risk:** 1% max per trade
**Support:** @{SUPPORT_HANDLE}"""
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['mt4'])
def mt4_cmd(message):
    uid = message.from_user.id
    if uid!= ADMIN_ID and (uid not in subscribers or not subscribers.get(uid)):
        bot.reply_to(message, f"🔒 Subscribers only. Pay Ksh {PRICING['lite']}")
        return

    account_balance = DEFAULT_ACCOUNT_BALANCE
    parts = message.text.split()
    if len(parts) > 1:
        try: account_balance = float(parts[1])
        except: pass

    bot.reply_to(message, f"🔍 Scanning for MT4 setup...\nAccount: ${account_balance}")
    settings = get_user_settings(uid)
    _, min_conf, _ = get_user_mode(uid)

    for symbol in settings['pairs']:
        results = check_all_strategies(symbol, min_conf=min_conf)
        if results:
            result = results[0]
            mt4_msg = format_mt4_signal(result, account_balance)
            bot.send_message(message.chat.id, mt4_msg, parse_mode='Markdown')
            return
    bot.send_message(message.chat.id, "❌ No A-grade setups in your selected pairs right now.\n\n*Patience > Losses*")

# ========= HEARTBEAT SYSTEM =========
def send_daily_heartbeat():
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == 6 and now.minute == 0:
            for uid, active in list(subscribers.items()):
                if not active: continue
                if uid in SUB_EXPIRY and SUB_EXPIRY[uid] < now:
                    subscribers[uid] = False
                    try:
                        bot.send_message(uid, "❌ **Subscription Expired**\n\nRenew to continue receiving signals.", parse_mode='Markdown')
                    except: pass
                    continue

                last_hb = LAST_HEARTBEAT.get(uid)
                if last_hb and last_hb.date() == now.date():
                    continue

                settings = get_user_settings(uid)
                mode_name, _, _ = get_user_mode(uid)
                signals_24h = SIGNALS_SENT_24H.get(uid, 0)

                try:
                    bot.send_message(uid, f"""**Scanner Active** ✅

📡 Scanning {len(settings['pairs'])} pairs 24/7
🎯 Mode: {mode_name}
⏰ Last 24h: {signals_24h} signals fired

*No setups = No trades. Patience pays.*""", parse_mode='Markdown')
                    LAST_HEARTBEAT[uid] = now
                    SIGNALS_SENT_24H[uid] = 0
                except: pass
            save_data()
            time.sleep(60)
        time.sleep(30)

# ========= AUTO SCANNER =========
def auto_scan():
    signals_today = 0
    last_reset = datetime.now(timezone.utc).date()

    while True:
        time.sleep(SCAN_INTERVAL)

        # Reset daily counter
        now = datetime.now(timezone.utc)
        if now.date() > last_reset:
            signals_today = 0
            last_reset = now.date()

        if signals_today >= MAX_SIGNALS_PER_DAY:
            continue

        for uid, active in list(subscribers.items()):
            if not active and uid!= ADMIN_ID: continue
            if uid in SUB_EXPIRY and SUB_EXPIRY[uid] < datetime.now(timezone.utc):
                subscribers[uid] = False
                continue

            settings = get_user_settings(uid)
            mode_name, min_conf, tier = get_user_mode(uid)

            for symbol in settings['pairs']:
                if signals_today >= MAX_SIGNALS_PER_DAY:
                    break

                results = check_all_strategies(symbol, min_conf=min_conf)

                for result in results:
                    if signals_today >= MAX_SIGNALS_PER_DAY:
                        break
                    if result['confluence'] < min_conf: continue

                    signal_key = f"{result['symbol']}_{result['dir']}_{min_conf}"
                    if signal_key in LAST_SIGNAL:
                        if (datetime.now(timezone.utc) - LAST_SIGNAL[signal_key]).seconds < 300: continue
                    LAST_SIGNAL[signal_key] = datetime.now(timezone.utc)

                    SIGNALS_SENT_24H[uid] = SIGNALS_SENT_24H.get(uid, 0) + 1
                    mt4_msg = format_mt4_signal(result, DEFAULT_ACCOUNT_BALANCE)

                    send_signal_to_user(uid, result, mt4_msg, mode_name, min_conf)
                    send_signal_to_channel(result, mt4_msg, mode_name, min_conf)

                    signals_today += 1
                    save_data()

# ========= START BOT =========
if __name__ == '__main__':
    print("Denverlyk V3.1 SUPER ELITE Starting...", flush=True)
    load_data()
    threading.Thread(target=auto_scan, daemon=True).start()
    threading.Thread(target=send_daily_heartbeat, daemon=True).start()
    print("Auto Scanner: ON", flush=True)
    print("Heartbeat System: ON", flush=True)
    print("Channel Posting: ON" if CHANNEL_ID else "Channel Posting: OFF", flush=True)
    print("12Data Rate Limit: 7 calls/min", flush=True)
    print("Bot Ready 🔥", flush=True)

    while True:
        try:
            bot.infinity_polling(none_stop=True, interval=1, timeout=60)
        except Exception as e:
            print(f"Bot crashed: {e}", flush=True)
            time.sleep(10)
