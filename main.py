import telebot
from telebot import types
from datetime import datetime, timedelta, timezone
import threading
import time
import requests
import numpy as np
import os

# ======== CONFIG - USES RAILWAY VARIABLES ========
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER')
WEEKLY_PRICE = 700
TWELVEDATA_API_KEY = os.getenv('TWELVEDATA_API_KEY')
TOKEN = os.getenv('BOT_TOKEN')
SUPPORT_HANDLE = os.getenv('SUPPORT_HANDLE')

CRYPTO_PAIRS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'DOGE']
FOREX_PAIRS = ['EUR/USD', 'GBP/USD', 'USD/JPY']
GOLD_PAIRS = ['XAU/USD']
INDEX_PAIRS = ['US30']

SCAN_INTERVAL = 120
MIN_CONFLUENCE = 5
MIN_CONFLUENCE_POCKET = 6
MIN_CONFLUENCE_BOOSTER = 4
BINANCE_SYMBOLS = [f'{p}USDT' for p in CRYPTO_PAIRS]
bot = telebot.TeleBot(TOKEN)

DEFAULT_ACCOUNT_BALANCE = 1000
REF_BONUS_DAYS = 3

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

def get_user_settings(uid):
    if uid not in USER_SETTINGS:
        USER_SETTINGS[uid] = {
            'crypto': True,
            'forex': True,
            'gold': True,
            'indices': True
        }
    return USER_SETTINGS[uid]

# ========= MT4/MT5 HELPER =========
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
        elif 'BTC' in symbol:
            pips = pip_diff
            lot_size = risk_amount / (pips * 1.0) if pips!= 0 else 0.01
        elif 'US30' in symbol or 'NAS' in symbol or 'US100' in symbol:
            pips = pip_diff
            lot_size = risk_amount / (pips * 1.0) if pips!= 0 else 0.01
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

# ========= TECHNICAL ANALYSIS =========
def safe_request(url, timeout=8):
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        print(f"REQUEST FAIL: {url[:50]} | {str(e)[:50]}", flush=True)
        return None

def get_binance_klines(symbol, interval='1h', limit=200):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    return safe_request(url)

def get_twelvedata_klines(symbol, interval='1h', limit=200):
    if not TWELVEDATA_API_KEY:
        return None

    td_interval = interval.replace('m', 'min').replace('d', 'day')
    url = f'https://api.twelvedata.com/time_series?symbol={symbol}&interval={td_interval}&outputsize={limit}&apikey={TWELVEDATA_API_KEY}'
    data = safe_request(url)
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

def get_klines(symbol, interval='1h', limit=200):
    if '/' in symbol or symbol in ['US30', 'XAU/USD']:
        return get_twelvedata_klines(symbol, interval, limit)
    else:
        return get_binance_klines(symbol, interval, limit)

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
    macd_long = i30m['macd'] > i30m['signal'] and i4h['ema21'] > i4h['ema50']
    macd_short = i30m['macd'] < i30m['signal'] and i4h['ema21'] < i4h['ema50']
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
        strategies.append({'name': 'Denverlyk ELITE', 'dir': 'LONG', 'action': 'BUY',
            'sl': sl, 'tp1': tp1, 'tp2': tp2, 'confluence': confluence_count(conditions_long), 'price': price, 'symbol': symbol})

    conditions_short = [triple_bear, bias_short, macd_short, vwap_short, rsi_short, vol_short]
    if confluence_count(conditions_short) >= min_conf:
        if '/' in symbol or 'US30' in symbol or 'XAU' in symbol:
            sl = price * 1.002; tp1 = price * 0.996; tp2 = price * 0.992
        else:
            sl = price*1.012; tp1 = price*0.98; tp2 = price*0.96
        strategies.append({'name': 'Denverlyk ELITE', 'dir': 'SHORT', 'action': 'SELL',
            'sl': sl, 'tp1': tp1, 'tp2': tp2, 'confluence': confluence_count(conditions_short), 'price': price, 'symbol': symbol})

    return strategies

def get_asset_type(symbol):
    if 'USDT' in symbol: return 'crypto'
    if symbol in ['XAU/USD']: return 'gold'
    if symbol in ['US30']: return 'indices'
    if '/' in symbol: return 'forex'
    return 'crypto'

def get_user_mode(uid):
    if uid in POCKET_USERS: return "ELITE 6/6", MIN_CONFLUENCE_POCKET
    if uid in POCKET_LITE_USERS: return "LITE 5/6", MIN_CONFLUENCE
    if uid in BOOSTER_USERS: return "BOOSTER 4/6", MIN_CONFLUENCE_BOOSTER
    return "STANDARD 5/6", MIN_CONFLUENCE

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

    if uid == ADMIN_ID:
        bot.reply_to(message, f"**Welcome Owner** 👑\n\nV2.6 ELITE PRO Online\n\nUse /menu", parse_mode='Markdown')
    else:
        if uid not in subscribers or not subscribers.get(uid):
            bot.reply_to(message, f"""**Denverlyk ELITE PRO** 🔥

**A-Grade Signals 24/7**
Crypto + Forex + Gold + Indices + MT4

**Expected Signal Volume:**
👑 ELITE 6/6: 1-4 total signals/week
💎 Standard 5/6: 5-12 total signals/week
⚡ Booster 4/6: 10-20 total signals/week

**1. Subscribe**
Send Ksh {WEEKLY_PRICE} to: **{MPESA_NUMBER}**

**2. Confirm**
Tap /confirm after payment

*Questions? Tap /help*""", parse_mode='Markdown')
        else:
            menu(message)

@bot.message_handler(commands=['menu'])
def menu(message):
    uid = message.from_user.id
    if uid!= ADMIN_ID and (uid not in subscribers or not subscribers.get(uid)):
        bot.reply_to(message, f"🔒 **Subscribe First**\n\nSend Ksh {WEEKLY_PRICE} to {MPESA_NUMBER}\nThen tap /confirm")
        return

    settings = get_user_settings(uid)
    mode_name, _ = get_user_mode(uid)
    pocket_elite = "🟢 ON" if uid in POCKET_USERS else "🔴 OFF"
    pocket_lite = "🟢 ON" if uid in POCKET_LITE_USERS else "🔴 OFF"
    booster = "🟢 ON" if uid in BOOSTER_USERS else "🔴 OFF"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📲 Get Signal Now", callback_data='signal_now'),
        types.InlineKeyboardButton("⚙️ Asset Filters", callback_data='assets'),
        types.InlineKeyboardButton(f"👑 Pocket ELITE {pocket_elite}", callback_data='pocket_elite'),
        types.InlineKeyboardButton(f"💎 Pocket Lite {pocket_lite}", callback_data='pocket_lite'),
        types.InlineKeyboardButton(f"⚡ Booster Mode {booster}", callback_data='booster'),
        types.InlineKeyboardButton("📊 MT4 Lot Calc", callback_data='mt4'),
        types.InlineKeyboardButton("📈 My Stats", callback_data='stats'),
        types.InlineKeyboardButton("💬 Support", url=f'https://t.me/{SUPPORT_HANDLE}')
    )

    bot.send_message(
        message.chat.id,
        f"""**DENVERLYK ELITE PRO** 🔥

**Status:** Active ✅
**Mode:** {mode_name}

**Signal Modes:**
👑 ELITE 6/6: 1-4/week | A-grade
💎 Lite 5/6: 5-12/week | B-grade
⚡ Booster 4/6: 10-20/week | C-grade

*Not enough signals? Try Booster 4/6 mode*""",
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

    elif call.data == 'assets':
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"{'🟢' if settings['crypto'] else '🔴'} Crypto", callback_data='toggle_crypto'),
            types.InlineKeyboardButton(f"{'🟢' if settings['forex'] else '🔴'} Forex", callback_data='toggle_forex'),
            types.InlineKeyboardButton(f"{'🟢' if settings['gold'] else '🔴'} Gold", callback_data='toggle_gold'),
            types.InlineKeyboardButton(f"{'🟢' if settings['indices'] else '🔴'} Indices", callback_data='toggle_indices'),
            types.InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')
        )
        bot.edit_message_text("**Asset Filters** ⚙️\n\nTap to toggle ON/OFF:\n\n*You'll only get signals for ON assets*",
                             call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

    elif call.data.startswith('toggle_'):
        asset = call.data.split('_')[1]
        settings[asset] = not settings[asset]
        bot.answer_callback_query(call.id, f"{asset.upper()} {'ON' if settings[asset] else 'OFF'}")
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"{'🟢' if settings['crypto'] else '🔴'} Crypto", callback_data='toggle_crypto'),
            types.InlineKeyboardButton(f"{'🟢' if settings['forex'] else '🔴'} Forex", callback_data='toggle_forex'),
            types.InlineKeyboardButton(f"{'🟢' if settings['gold'] else '🔴'} Gold", callback_data='toggle_gold'),
            types.InlineKeyboardButton(f"{'🟢' if settings['indices'] else '🔴'} Indices", callback_data='toggle_indices'),
            types.InlineKeyboardButton("◀️ Back to Menu", callback_data='menu')
        )
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data == 'pocket_elite':
        if user_id!= ADMIN_ID and (user_id not in subscribers or not subscribers.get(user_id)):
            bot.answer_callback_query(call.id, "Subscribe first!", show_alert=True)
            return
        if user_id in POCKET_USERS:
            POCKET_USERS.remove(user_id)
            bot.answer_callback_query(call.id, "Pocket ELITE OFF")
        else:
            POCKET_USERS.add(user_id)
            POCKET_LITE_USERS.discard(user_id)
            BOOSTER_USERS.discard(user_id)
            bot.answer_callback_query(call.id, "Pocket ELITE ON - 6/6 only")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        menu(call.message)

    elif call.data == 'pocket_lite':
        if user_id!= ADMIN_ID and (user_id not in subscribers or not subscribers.get(user_id)):
            bot.answer_callback_query(call.id, "Subscribe first!", show_alert=True)
            return
        if user_id in POCKET_LITE_USERS:
            POCKET_LITE_USERS.remove(user_id)
            bot.answer_callback_query(call.id, "Pocket Lite OFF")
        else:
            POCKET_LITE_USERS.add(user_id)
            POCKET_USERS.discard(user_id)
            BOOSTER_USERS.discard(user_id)
            bot.answer_callback_query(call.id, "Pocket Lite ON - 5/6 only")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        menu(call.message)

    elif call.data == 'booster':
        if user_id!= ADMIN_ID and (user_id not in subscribers or not subscribers.get(user_id)):
            bot.answer_callback_query(call.id, "Subscribe first!", show_alert=True)
            return
        if user_id in BOOSTER_USERS:
            BOOSTER_USERS.remove(user_id)
            bot.answer_callback_query(call.id, "Booster OFF")
        else:
            BOOSTER_USERS.add(user_id)
            POCKET_USERS.discard(user_id)
            POCKET_LITE_USERS.discard(user_id)
            bot.answer_callback_query(call.id, "Booster ON - 4/6 B-grade")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        menu(call.message)

    elif call.data == 'mt4':
        bot.answer_callback_query(call.id)
        msg = """**MT4 Lot Size Calculator** 📊

Send command with your balance:
`/mt4 1000` → For $1,000 account
`/mt4 500` → For $500 account
`/mt4 10000` → For $10,000 account

*Bot auto-calculates 1% risk per trade*"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

    elif call.data == 'stats':
        expiry = SUB_EXPIRY.get(user_id)
        expiry_text = expiry.strftime('%d %b %Y') if expiry else "Lifetime"
        mode_name, _ = get_user_mode(user_id)
        signals_24h = SIGNALS_SENT_24H.get(user_id, 0)
        bot.answer_callback_query(call.id)
        msg = f"""**Your Stats** 📈

**Account:** Active ✅
**Expires:** {expiry_text}
**Mode:** {mode_name}
**Signals 24h:** {signals_24h}
**Crypto:** {"ON" if settings['crypto'] else "OFF"}
**Forex:** {"ON" if settings['forex'] else "OFF"}
**Gold:** {"ON" if settings['gold'] else "OFF"}
**Indices:** {"ON" if settings['indices'] else "OFF"}"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("◀️ Back to Menu", callback_data='menu'))
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

    elif call.data == 'menu':
        bot.answer_callback_query(call.id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        menu(call.message)

@bot.message_handler(commands=['mt4'])
def mt4_cmd(message):
    uid = message.from_user.id
    if uid!= ADMIN_ID and (uid not in subscribers or not subscribers.get(uid)):
        bot.reply_to(message, f"🔒 Subscribers only. Pay Ksh {WEEKLY_PRICE}")
        return

    account_balance = DEFAULT_ACCOUNT_BALANCE
    parts = message.text.split()
    if len(parts) > 1:
        try: account_balance = float(parts[1])
        except: pass

    bot.reply_to(message, f"🔍 Scanning for MT4 setup...\nAccount: ${account_balance}")
    all_pairs = BINANCE_SYMBOLS + FOREX_PAIRS + GOLD_PAIRS + INDEX_PAIRS
    settings = get_user_settings(uid)
    _, min_conf = get_user_mode(uid)

    for symbol in all_pairs:
        asset_type = get_asset_type(symbol)
        if not settings.get(asset_type, True): continue

        results = check_all_strategies(symbol, min_conf=min_conf)
        if results:
            result = results[0]
            mt4_msg = format_mt4_signal(result, account_balance)
            bot.send_message(message.chat.id, mt4_msg, parse_mode='Markdown')
            return
    bot.send_message(message.chat.id, "❌ No A-grade setups right now.\n\n*Patience > Losses*")

@bot.message_handler(commands=['signal'])
def manual_signal(message):
    uid = message.from_user.id
    if uid!= ADMIN_ID:
        if uid not in subscribers or not subscribers.get(uid):
            bot.reply_to(message, f"🔒 Subscribers only. Pay Ksh {WEEKLY_PRICE}")
            return

    settings = get_user_settings(uid)
    all_pairs = []
    if settings['crypto']: all_pairs.extend(BINANCE_SYMBOLS)
    if settings['forex']: all_pairs.extend(FOREX_PAIRS)
    if settings['gold']: all_pairs.extend(GOLD_PAIRS)
    if settings['indices']: all_pairs.extend(INDEX_PAIRS)

    if not all_pairs:
        bot.reply_to(message, "❌ All assets OFF. Go to /menu → Asset Filters to enable.")
        return

    mode_name, min_conf = get_user_mode(uid)
    bot.reply_to(message, f"🔍 Scanning {len(all_pairs)} pairs | Mode: {mode_name}...")
    signals_found = 0
    for symbol in all_pairs:
        results = check_all_strategies(symbol, min_conf=min_conf)
        for result in results:
            if result['confluence'] < min_conf: continue

            signals_found += 1
            SIGNALS_SENT_24H[uid] = SIGNALS_SENT_24H.get(uid, 0) + 1
            mt4_msg = format_mt4_signal(result, DEFAULT_ACCOUNT_BALANCE)
            asset_name = result['symbol'].replace('USDT','').replace('/','')
            emoji = "🟢" if result['dir'] == 'LONG' else "🔴"
            grade = "A-GRADE" if min_conf >= 5 else "B-GRADE"
            msg = f"""**DENVERLYK ELITE PRO SIGNAL** 🔥

{emoji} **{asset_name} {result['dir']}** | {grade}
**Action:** {result['action']}
**Confluence:** {result['confluence']}/6

**Entry:** {result['price']:.5f}
**SL:** {result['sl']:.5f}
**TP1:** {result['tp1']:.5f}
**TP2:** {result['tp2']:.5f}

{mt4_msg}

*Risk 1% max. No revenge trades.*"""
            bot.send_message(message.chat.id, msg, parse_mode='Markdown')
            if signals_found >= 3: return
    if signals_found == 0:
        bot.send_message(message.chat.id, f"❌ No {mode_name} setups right now.\n\n*Patience > Losses. Scanner running 24/7*\n\n*Want more signals? Try Booster Mode 4/6*")

@bot.message_handler(commands=['confirm'])
def confirm(message):
    uid = message.from_user.id
    if uid == ADMIN_ID:
        bot.reply_to(message, "Unlimited access, sir.")
        return
    bot.reply_to(message, "Send M-Pesa confirmation screenshot here. Admin activates in 5min.")
    bot.send_message(ADMIN_ID, f"⚠️ **Payment Claim**\n\nUser: @{message.from_user.username} ({uid})\n\nReply: /activate {uid}")

@bot.message_handler(commands=['activate'])
def activate(message):
    if message.from_user.id!= ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        subscribers[user_id] = True
        SUB_EXPIRY[user_id] = datetime.now(timezone.utc) + timedelta(days=7)
        get_user_settings(user_id)
        SIGNALS_SENT_24H[user_id] = 0
        if user_id in REF_MAP:
            referrer = REF_MAP[user_id]
            PENDING_CREDIT[referrer] = PENDING_CREDIT.get(referrer, 0) + REF_BONUS_DAYS
            if referrer in SUB_EXPIRY:
                SUB_EXPIRY[referrer] += timedelta(days=REF_BONUS_DAYS)
            else:
                SUB_EXPIRY[referrer] = datetime.now(timezone.utc) + timedelta(days=REF_BONUS_DAYS)
                subscribers[referrer] = True
            bot.send_message(referrer, f"🎉 **Referral Bonus!**\n\n+{REF_BONUS_DAYS} days added.\nNew expiry: {SUB_EXPIRY[referrer].strftime('%d %b %Y')}")

        bot.send_message(user_id, f"""✅ **Payment Confirmed!**

Denverlyk V2.6 ELITE PRO activated.
Expires: {SUB_EXPIRY[user_id].strftime('%d %b %Y')}

**SIGNAL VOLUME - READ CAREFULLY:**

**👑 ELITE 6/6 Mode:** 0-1 signals/day | 1-4/week
**💎 LITE 5/6 Mode:** 0-2 signals/day | 5-12/week
**⚡ BOOSTER 4/6 Mode:** 1-3 signals/day | 10-20/week

*Zero signals for days is NORMAL in ELITE mode*
*No signal = Market choppy = Capital protected*

Tap /menu to start""", parse_mode='Markdown')
        bot.reply_to(message, f"Activated {user_id} for 7 days.")
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)[:100]}")

@bot.message_handler(commands=['referral'])
def referral(message):
    uid = message.from_user.id
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
    earned_days = PENDING_CREDIT.get(uid, 0)
    total_refs = len(REFERRALS.get(uid, []))

    bot.reply_to(message, f"""**Your Referral Link:** 🔗
`{ref_link}`

**Rewards:** +{REF_BONUS_DAYS} days per paid referral
**Earned:** {earned_days} days
**Total Referrals:** {total_refs}

*Share it. Get paid in time* 👊""", parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_cmd(message):
    help_text = f"""**DENVERLYK ELITE PRO HELP** 🆘

**Trading Commands:**
/menu - Main dashboard
/signal - Force scan now
/mt4 1000 - MT4 lot calc for $1000

**Signal Modes:**
👑 ELITE 6/6 - 1-4/week | A-grade only
💎 LITE 5/6 - 5-12/week | Standard
⚡ BOOSTER 4/6 - 10-20/week | B-grade

**Asset Control:**
/menu → Asset Filters - Toggle Crypto/Forex/Gold/Indices

**Account:**
/referral - Invite friends, earn days
/confirm - Submit payment proof

**Risk:** 1% max per trade
**Price:** Ksh {WEEKLY_PRICE}/week"""
    bot.reply_to(message, help_text, parse_mode='Markdown')

# ========= HEARTBEAT SYSTEM =========
def send_daily_heartbeat():
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == 6 and now.minute == 0:
            for uid, active in subscribers.items():
                if not active: continue
                if uid in SUB_EXPIRY and SUB_EXPIRY[uid] < now:
                    subscribers[uid] = False
                    continue

                last_hb = LAST_HEARTBEAT.get(uid)
                if last_hb and last_hb.date() == now.date():
                    continue

                settings = get_user_settings(uid)
                asset_count = sum(1 for v in settings.values() if v)
                mode_name, _ = get_user_mode(uid)
                signals_24h = SIGNALS_SENT_24H.get(uid, 0)

                try:
                    bot.send_message(uid, f"""**Scanner Active** ✅

📡 Scanning {asset_count} asset types 24/7
🎯 Mode: {mode_name}
⏰ Last 24h: {signals_24h} signals fired

*No setups = No trades. Patience pays.*
*Want more signals? Try Booster Mode in /menu*""", parse_mode='Markdown')
                    LAST_HEARTBEAT[uid] = now
                    SIGNALS_SENT_24H[uid] = 0
                except: pass
            time.sleep(60)
        time.sleep(30)

# ========= AUTO SCANNER =========
def auto_scan():
    while True:
        time.sleep(SCAN_INTERVAL)
        all_symbols = BINANCE_SYMBOLS + FOREX_PAIRS + GOLD_PAIRS + INDEX_PAIRS

        for symbol in all_symbols:
            asset_type = get_asset_type(symbol)

            for uid, active in subscribers.items():
                if not active and uid!= ADMIN_ID: continue
                if uid in SUB_EXPIRY and SUB_EXPIRY[uid] < datetime.now(timezone.utc):
                    subscribers[uid] = False
                    continue

                settings = get_user_settings(uid)
                if not settings.get(asset_type, True): continue

                mode_name, min_conf = get_user_mode(uid)
                results = check_all_strategies(symbol, min_conf=min_conf)

                for result in results:
                    if result['confluence'] < min_conf: continue

                    signal_key = f"{result['symbol']}_{result['dir']}_{min_conf}"
                    if signal_key in LAST_SIGNAL:
                        if (datetime.now(timezone.utc) - LAST_SIGNAL[signal_key]).seconds < 300: continue
                    LAST_SIGNAL[signal_key] = datetime.now(timezone.utc)

                    SIGNALS_SENT_24H[uid] = SIGNALS_SENT_24H.get(uid, 0) + 1
                    mt4_msg = format_mt4_signal(result, DEFAULT_ACCOUNT_BALANCE)
                    asset_name = result['symbol'].replace('USDT','').replace('/','')
                    emoji = "🟢" if result['dir'] == 'LONG' else "🔴"
                    grade = "A-GRADE" if min_conf >= 5 else "B-GRADE"
                    header = "👑 DENVERLYK ELITE 6/6" if min_conf == 6 else f"DENVERLYK ELITE PRO {mode_name}"

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
                        print(f"SIGNAL SENT to {uid}: {asset_name} {result['dir']}", flush=True)
                    except Exception as e:
                        print(f"Failed to send to {uid}: {str(e)[:50]}", flush=True)

# ========= START BOT =========
if __name__ == '__main__':
    print("Denverlyk V2.6 ELITE PRO Starting...", flush=True)
    threading.Thread(target=auto_scan, daemon=True).start()
    threading.Thread(target=send_daily_heartbeat, daemon=True).start()
    print("Auto Scanner: ON", flush=True)
    print("Heartbeat System: ON", flush=True)
    print("Bot Ready 🔥", flush=True)
    
    while True:
        try:
            bot.infinity_polling(none_stop=True, interval=1, timeout=60)
        except Exception as e:
            print(f"Bot crashed: {e}", flush=True)
            time.sleep(10)
