import os
import telebot
from telebot import types
from datetime import datetime, timedelta, timezone
import requests
import time

# === CONFIG ===
BOT_TOKEN = os.getenv('BOT_TOKEN')
TWELVE_DATA_KEY = os.getenv('TWELVE_DATA_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
MPESA_NUMBER = os.getenv('MPESA_NUMBER', 'Contact Admin')
EAT = 3 # GMT+3

bot = telebot.TeleBot(BOT_TOKEN)

# === DATABASE ===
subscribers = {}
trade_history = {}
daily_trades = {}
pair_cooldowns = {}
active_signals = {}

# === HELPER FUNCTIONS ===
def now_eat():
    return datetime.now(timezone.utc) + timedelta(hours=EAT)

def is_admin(user_id):
    return user_id == ADMIN_ID

def has_access(user_id):
    if is_admin(user_id):
        return True
    if user_id not in subscribers:
        return False
    return subscribers[user_id]['expiry'] > now_eat()

def can_trade(user_id):
    today = now_eat().date()
    if user_id not in daily_trades:
        daily_trades[user_id] = {}
    if today not in daily_trades[user_id]:
        daily_trades[user_id][today] = 0
    return daily_trades[user_id][today] < 10

def on_cooldown(symbol):
    if symbol in pair_cooldowns:
        return time.time() - pair_cooldowns[symbol] < 60
    return False

def set_cooldown(symbol):
    pair_cooldowns[symbol] = time.time()

def get_candles(symbol, interval='5min', outputsize=200):
    try:
        url = f'https://api.twelvedata.com/time_series'
        params = {
            'symbol': symbol,
            'interval': interval,
            'outputsize': outputsize,
            'apikey': TWELVE_DATA_KEY
        }
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if 'values' in data:
            return data['values'][::-1]
        else:
            print(f"TwelveData error: {data}")
            return None
    except Exception as e:
        print(f"TwelveData exception: {e}")
        return None

def calculate_rsi(candles, period=14):
    closes = [float(c['close']) for c in candles]
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_sma(candles, period=20):
    closes = [float(c['close']) for c in candles]
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    tr_list = []
    for i in range(1, len(candles)):
        high = float(candles[i]['high'])
        low = float(candles[i]['low'])
        prev_close = float(candles[i-1]['close'])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

    return sum(tr_list[-period:]) / period

def generate_signal(symbol):
    candles = get_candles(symbol, '5min', 200)
    if not candles or len(candles) < 50:
        return None, "API error - no data"

    rsi = calculate_rsi(candles)
    sma = calculate_sma(candles, 20)
    atr = calculate_atr(candles)
    current_price = float(candles[-1]['close'])
    prev_price = float(candles[-2]['close'])

    if not all([rsi, sma, atr]):
        return None, "Calculation error"

    signal = None
    confidence = 50

    if rsi < 35 and current_price > sma and current_price > prev_price:
        signal = "CALL"
        confidence = 65 + (35 - rsi)
    elif rsi > 65 and current_price < sma and current_price < prev_price:
        signal = "PUT"
        confidence = 65 + (rsi - 65)

    if not signal:
        return None, "No setup - market is choppy"

    if signal == "CALL":
        sl = current_price - (atr * 1.5)
        tp = current_price + (atr * 2.0)
    else:
        sl = current_price + (atr * 1.5)
        tp = current_price - (atr * 2.0)

    confidence = min(confidence, 85)

    if confidence < 65:
        return None, f"No setup - confidence too low: {confidence}%"

    return {
        'symbol': symbol,
        'direction': signal,
        'entry': round(current_price, 5),
        'sl': round(sl, 5),
        'tp': round(tp, 5),
        'confidence': round(confidence, 1),
        'rsi': round(rsi, 1),
        'expiry': '5min'
    }, None

# === KEYBOARDS ===
def main_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    trades_left = 10 - daily_trades.get(user_id, {}).get(now_eat().date(), 0)

    markup.add(
        types.InlineKeyboardButton(f"🔥 Get Signal ({trades_left} left)", callback_data="pick_pair")
    )
    markup.row(
        types.InlineKeyboardButton("📈 Mode: PO", callback_data="mode"),
        types.InlineKeyboardButton("🤖 Auto: OFF", callback_data="auto")
    )
    markup.row(
        types.InlineKeyboardButton("📊 My Stats", callback_data="stats"),
        types.InlineKeyboardButton("🧮 Calculator", callback_data="calc")
    )
    if is_admin(user_id):
        markup.add(types.InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel"))

    return markup

def pair_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    pairs = [
        ("🟠 XAUUSD", "XAU/USD"),
        ("🇪🇺 EURUSD", "EUR/USD"),
        ("🇬🇧 GBPUSD", "GBP/USD"),
        ("💻 BTCUSD", "BTC/USD")
    ]
    buttons = [types.InlineKeyboardButton(name, callback_data=f"scan_{sym}") for name, sym in pairs]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="main_menu"))
    return markup

def admin_panel_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats"),
        types.InlineKeyboardButton("👥 Users", callback_data="users")
    )
    markup.row(
        types.InlineKeyboardButton("🔧 API Status", callback_data="api_status"),
        types.InlineKeyboardButton("🔴 Kill Switch", callback_data="kill")
    )
    markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="main_menu"))
    return markup

# === COMMANDS ===
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    if not has_access(user_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ I've Paid - Activate Me", callback_data="check_payment"))
        bot.reply_to(message, f"""
🚀 **Denverlyk Trading Bot V3.4**

⚡ Pick-A-Pair System
🎯 ATR-based SL/TP
📊 65%+ Confidence Filter
🛡️ Max 10 trades/day

💵 **M-Pesa:** `{MPESA_NUMBER}`
💰 **7 Days Access: 2000 KSH**

1. Send payment to number above
2. Tap "I've Paid" button
3. Wait for admin approval
""", reply_markup=markup, parse_mode='Markdown')
        return

    bot.reply_to(message, f"✅ Welcome back!\n\nTrades left today: {10 - daily_trades.get(user_id, {}).get(now_eat().date(), 0)}/10", reply_markup=main_menu(user_id))

@bot.message_handler(commands=['adduser'])
def add_user(message):
    if not is_admin(message.from_user.id):
        return
    try:
        parts = message.text.split()
        target_id = int(parts[1])
        days = int(parts[2])
        expiry = now_eat() + timedelta(days=days)
        subscribers[target_id] = {'expiry': expiry, 'added': now_eat()}
        bot.reply_to(message, f"✅ User {target_id} added\nExpiry: {expiry.strftime('%Y-%m-%d')}")
        try:
            bot.send_message(target_id, f"✅ **Access Activated!**\n\nYour subscription is live until {expiry.strftime('%Y-%m-%d')}.\n\nSend /start to begin.", parse_mode='Markdown')
        except:
            pass
    except:
        bot.reply_to(message, "❌ Usage: /adduser USER_ID DAYS")

@bot.message_handler(commands=['myid'])
def my_id(message):
    bot.reply_to(message, f"Your User ID: `{message.from_user.id}`\n\nSend this to admin after payment", parse_mode='Markdown')

@bot.message_handler(commands=['api'])
def api_check(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ Admin only")
        return

    bot.reply_to(message, "🔍 Testing TwelveData...")
    try:
        data = get_candles('EUR/USD', '5min', 5)
        if data and len(data) > 0:
            bot.reply_to(message, f"✅ **TwelveData: ONLINE**\n\nCandles received: {len(data)}\nLast price: {data[-1]['close']}\nTime: {now_eat().strftime('%H:%M:%S EAT')}", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"⚠️ **TwelveData: NO DATA**\n\nAPI connected but returned 0 candles\nMarket might be closed", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ **TwelveData: ERROR**\n\n{str(e)[:200]}", parse_mode='Markdown')

@bot.message_handler(commands=['scan'])
def scan_command(message):
    user_id = message.from_user.id
    if not has_access(user_id):
        bot.reply_to(message, "❌ No access. Use /start")
        return
    if not can_trade(user_id):
        bot.reply_to(message, "❌ Daily limit reached: 10/10")
        return

    try:
        symbol = message.text.split()[1].upper().replace('/', '')
        if symbol == 'XAUUSD':
            symbol = 'XAU/USD'
        elif symbol == 'EURUSD':
            symbol = 'EUR/USD'
        elif symbol == 'GBPUSD':
            symbol = 'GBP/USD'
        elif symbol == 'BTCUSD':
            symbol = 'BTC/USD'
    except:
        bot.reply_to(message, "❌ Usage: /scan XAUUSD")
        return

    if on_cooldown(symbol):
        bot.reply_to(message, f"❌ {symbol} on 60s cooldown")
        return

    msg = bot.reply_to(message, f"🔍 Scanning {symbol}...")
    set_cooldown(symbol)

    signal, error = generate_signal(symbol)

    if error:
        bot.edit_message_text(f"❌ No setup for {symbol}\n{error}", msg.chat.id, msg.message_id)
        return

    signal_id = f"{user_id}_{int(time.time())}"
    active_signals[signal_id] = signal

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ WIN", callback_data=f"win_{signal_id}"),
        types.InlineKeyboardButton("❌ LOSS", callback_data=f"loss_{signal_id}")
    )

    bot.edit_message_text(f"""
🎯 **{signal['symbol']} - {signal['direction']}**

📊 Entry: {signal['entry']}
🛑 SL: {signal['sl']}
🎯 TP: {signal['tp']}
⏱️ {signal['expiry']} expiry
💪 Confidence: {signal['confidence']}%
📈 RSI: {signal['rsi']}

Mark result after trade closes:
""", msg.chat.id, msg.message_id, reply_markup=markup, parse_mode='Markdown')

# === CALLBACKS ===
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data

    if data == "check_payment":
        bot.answer_callback_query(call.id, "Request sent to admin")
        bot.send_message(ADMIN_ID, f"💰 **Payment Check**\n\nUser: @{call.from_user.username}\nID: `{user_id}`\nName: {call.from_user.first_name}\n\nActivate with: `/adduser {user_id} 7`", parse_mode='Markdown')
        bot.edit_message_text(f"✅ **Request Sent**\n\nAdmin will verify payment and activate you.\n\nYour ID: `{user_id}`\n\nYou'll get a message when approved.", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

    elif data == "main_menu":
        bot.edit_message_text(f"✅ Welcome back!\n\nTrades left today: {10 - daily_trades.get(user_id, {}).get(now_eat().date(), 0)}/10",
                              call.message.chat.id, call.message.message_id, reply_markup=main_menu(user_id))

    elif data == "pick_pair":
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ No access")
            return
        if not can_trade(user_id):
            bot.answer_callback_query(call.id, "❌ Daily limit reached")
            return
        bot.edit_message_text("🎯 **Pick a pair to scan:**\n\n60s cooldown per pair",
                              call.message.chat.id, call.message.message_id, reply_markup=pair_menu(), parse_mode='Markdown')

    elif data.startswith("scan_"):
        if not has_access(user_id):
            bot.answer_callback_query(call.id, "❌ No access")
            return
        if not can_trade(user_id):
            bot.answer_callback_query(call.id, "❌ Daily limit reached")
            return

        symbol = data.split("_")[1]
        if on_cooldown(symbol):
            bot.answer_callback_query(call.id, f"❌ {symbol} on cooldown")
            return

        bot.answer_callback_query(call.id, f"Scanning {symbol}...")
        bot.edit_message_text(f"🔍 Scanning {symbol}...\nPlease wait 5-10 seconds",
                              call.message.chat.id, call.message.message_id)
        set_cooldown(symbol)

        signal, error = generate_signal(symbol)

        if error:
            bot.edit_message_text(f"❌ No setup for {symbol}\n{error}",
                                  call.message.chat.id, call.message.message_id, reply_markup=pair_menu())
            return

        today = now_eat().date()
        if user_id not in daily_trades:
            daily_trades[user_id] = {}
        if today not in daily_trades[user_id]:
            daily_trades[user_id][today] = 0
        daily_trades[user_id][today] += 1

        signal_id = f"{user_id}_{int(time.time())}"
        active_signals[signal_id] = signal

        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ WIN", callback_data=f"win_{signal_id}"),
            types.InlineKeyboardButton("❌ LOSS", callback_data=f"loss_{signal_id}")
        )
        markup.add(types.InlineKeyboardButton("⬅️ Back", callback_data="pick_pair"))

        bot.edit_message_text(f"""
🎯 **{signal['symbol']} - {signal['direction']}**

📊 Entry: {signal['entry']}
🛑 SL: {signal['sl']}
🎯 TP: {signal['tp']}
⏱️ {signal['expiry']} expiry
💪 Confidence: {signal['confidence']}%
📈 RSI: {signal['rsi']}

Mark result after trade closes:
""", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

    elif data.startswith("win_") or data.startswith("loss_"):
        signal_id = data.split("_", 1)[1]
        if signal_id not in active_signals:
            bot.answer_callback_query(call.id, "❌ Signal expired")
            return

        result = "WIN" if data.startswith("win_") else "LOSS"
        signal = active_signals[signal_id]

        if user_id not in trade_history:
            trade_history[user_id] = []
        trade_history[user_id].append({
            'symbol': signal['symbol'],
            'direction': signal['direction'],
            'result': result,
            'time': now_eat()
        })
        del active_signals[signal_id]

        bot.answer_callback_query(call.id, f"Marked as {result}")
        bot.edit_message_text(f"✅ **{signal['symbol']} - {result}**\n\nSaved to stats.",
                              call.message.chat.id, call.message.message_id, reply_markup=pair_menu())

    elif data == "stats":
        if user_id not in trade_history or len(trade_history[user_id]) == 0:
            bot.answer_callback_query(call.id, "No trades yet")
            return
        trades = trade_history[user_id]
        wins = sum(1 for t in trades if t['result'] == 'WIN')
        total = len(trades)
        win_rate = round((wins/total)*100, 1) if total > 0 else 0

        bot.edit_message_text(f"""
📊 **Your Stats**

Total trades: {total}
✅ Wins: {wins}
❌ Losses: {total - wins}
🎯 Win Rate: {win_rate}%

Trades today: {daily_trades.get(user_id, {}).get(now_eat().date(), 0)}/10
""", call.message.chat.id, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("⬅️ Back", callback_data="main_menu")
        ), parse_mode='Markdown')

    elif data == "admin_panel":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Admin only")
            return
        bot.edit_message_text("👑 **Admin Panel**", call.message.chat.id, call.message.message_id,
                              reply_markup=admin_panel_menu(), parse_mode='Markdown')

    elif data == "api_status":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Admin only")
            return

        bot.answer_callback_query(call.id, "Testing API...")
        try:
            data = get_candles('EUR/USD', '5min', 5)
            if data and len(data) > 0:
                status = f"✅ **TwelveData: ONLINE**\n\nLast check: {now_eat().strftime('%H:%M:%S')}\nCandles: {len(data)}\nPrice: {data[-1]['close']}\nAPI Key: SET"
            else:
                status = f"⚠️ **TwelveData: NO DATA**\n\nConnected but 0 candles returned\nMarket might be closed"
        except Exception as e:
            status = f"❌ **TwelveData: ERROR**\n\n{str(e)[:150]}"

        bot.edit_message_text(status, call.message.chat.id, call.message.message_id,
                              reply_markup=types.InlineKeyboardMarkup().row(
                                  types.InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")
                              ), parse_mode='Markdown')

    elif data == "bot_stats":
        if not is_admin(user_id):
            return
        total_users = len(subscribers)
        total_trades = sum(len(h) for h in trade_history.values())
        bot.edit_message_text(f"""
📊 **Bot Stats**

👥 Total users: {total_users}
📈 Total trades logged: {total_trades}
🔥 Active signals: {len(active_signals)}
⏰ Uptime: {now_eat().strftime('%Y-%m-%d %H:%M EAT')}
""", call.message.chat.id, call.message.message_id,
                              reply_markup=types.InlineKeyboardMarkup().add(
                                  types.InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")
                              ), parse_mode='Markdown')

# === START ===
print("Denverlyk V3.4 PICK-A-PAIR Starting...")
print(f"Bot online: @Denverlykbot")
print(f"Admin: {ADMIN_ID}")
print("Safety: Max 10 trades/user/day | ATR SL/TP")
print("Scan: User-triggered | 60s cooldown")
print(f"TwelveData: {'SET' if TWELVE_DATA_KEY else 'MISSING'}")
print(f"M-Pesa: {MPESA_NUMBER}")

# Set Telegram Menu Button
bot.set_my_commands([
    telebot.types.BotCommand("/start", "🚀 Open main menu"),
    telebot.types.BotCommand("/myid", "🆔 Get your User ID"),
    telebot.types.BotCommand("/scan", "📊 Scan a pair: /scan XAUUSD"),
    telebot.types.BotCommand("/api", "🔧 Check API status (Admin)")
])

print("Menu button set")
bot.infinity_polling()
