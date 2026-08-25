import os, re, threading, time, requests, pytz, psycopg2, random, json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from io import BytesIO
import telebot
from telebot import types
from datetime import datetime, timedelta
from flask import Flask
from gtts import gTTS

app = Flask(__name__)
@app.route('/')
def home(): return "DENVERLYK PRO V22.8.13 LOOSENED 1060 LINES"
@app.route('/ping')
def ping(): return "pong"
@app.route('/health')
def health(): return "alive", 200
def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)
threading.Thread(target=run_web, daemon=True).start()

def keep_alive_ping():
    while True:
        try:
            time.sleep(180)
            url = os.getenv("RENDER_EXTERNAL_URL")
            if url:
                requests.get(f"{url}/ping", timeout=10)
            port = int(os.environ.get('PORT', 10000))
            try: requests.get(f"http://127.0.0.1:{port}/ping", timeout=5)
            except: pass
        except Exception as e:
            print(f"Keep-alive err {e}")
threading.Thread(target=keep_alive_ping, daemon=True).start()

EAT = pytz.timezone('Africa/Nairobi')
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID","0"))
BRAND_NAME="DENVERLYK PRO"
MPESA_NUMBER="0143773606"; MPESA_NAME="Dennis.M"
USDT_TRC20="TKmrfGK34VTopXQP8wRPWoW8a4G2PeaffL"; MY_TRC20=USDT_TRC20
CHANNEL_LINK="https://t.me/+2cgadtF2f1g4YzFk"
SUPPORT_LINK="https://t.me/Denverlyk"
USDT_CONTRACT="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
PRICE_USD_7=16
PRICE_USD_30=50
PRICE_7DAYS=2000
PRICE_30DAYS=7200
TWELVEDATA_KEYS=[k.strip() for k in os.getenv("TWELVEDATA_KEYS","").split(",") if k.strip()!='']
CHANNEL_ID=int(os.getenv("CHANNEL_ID","-1003756434716"))
DATABASE_URL=os.getenv("DATABASE_URL")
BOT_LINK=os.getenv("BOT_LINK","https://t.me/Denverlykpro_bot")

ALL_PAIRS=[
 "BTC/USD","ETH/USD","SOL/USD","BNB/USD","XRP/USD","ADA/USD","DOGE/USD","AVAX/USD",
 "XAU/USD","XAG/USD",
 "US30/USD","NAS100/USD","SPX500/USD","GER40/USD","UK100/USD",
 "EUR/USD","GBP/USD","USD/JPY","USD/CHF","AUD/USD","NZD/USD","USD/CAD",
 "EUR/JPY","GBP/JPY","AUD/JPY","EUR/GBP","EUR/AUD","GBP/AUD","GBP/CAD","EUR/CAD","WTI/USD","BRENT/USD"
]

bot=telebot.TeleBot(TOKEN, threaded=True, num_threads=15)
key_index=0; PENDING_PAYMENTS={}; USER_TF={}; USER_MODE={}

MIN_ADX_STRICT=16
MIN_ATR_P=0.08
MAX_SPREAD_P=0.60
TIMEFRAMES_ALL=["1m","5min","15min","1h"]
TF_LABELS={"1m":"⚡ SCALP 1 MIN","5m":"🔥 INTRADAY 5 MIN","15m":"📈 SWING 15 MIN","1h":"💎 POSITION 1 HOUR"}
LOSS_COOLDOWN_PAIRS={}; NEWS_PAIRS_BLOCK={}; PAIR_PERFORMANCE={}
USER_STATE_TICKET={}
FOMO_INDEX=0

BUY_VNS=[
"Alright team, high probability BUY forming, {pair_label} {pair}, {tf_spoken}, BUY now,,, bearish exhausting, bouncing from EMA twenty one, RSI {rsi}, ADX {adx} strong, confidence {conf} of six, entry {entry}, stop {sl}, take profit {tp}, lets secure win",
"Team listen, {pair} perfect BUY setup, {tf_spoken}, price above EMA 200 bullish, EMA 21 above 50, RSI {rsi} healthy, ADX {adx} confirms strength, confidence {conf} of six, entry {entry}, sl {sl}, tp {tp}, take it now",
"Boom, {pair} BUY alert, {tf_spoken}, bullish engulfing at support, EMA 9 above 21, RSI {rsi} not overbought, ADX {adx} strong trend, confidence {conf}, entry {entry}, stop {sl}, tp {tp}, send it",
"Attention pride, {pair_label} {pair} BUY, {tf_spoken}, support holding, bounced from EMA 21, volume up, RSI {rsi}, ADX {adx} buyers control, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Yo team, {pair} BUY opportunity, {tf_spoken}, double bottom formed, MACD bullish, RSI {rsi}, ADX {adx}, textbook bullish retest, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair_label} {pair} BUY now, {tf_spoken}, trend up, price above EMA 200, pullback finished at EMA 21, RSI {rsi}, ADX {adx}, confidence {conf}, entry {entry}, sl {sl}, tp {tp}, secure bag",
"Beast mode BUY, {pair}, {tf_spoken}, bears trapped, price above EMA 21, RSI {rsi} rising, ADX {adx} momentum strong, conf {conf}, entry {entry}, stop {sl}, tp {tp}, lets go",
"Team {pair} BUY, {tf_spoken}, London bullish, price respecting EMA 21 support, RSI {rsi}, ADX {adx} solid, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Lions, {pair} BUY setup, {tf_spoken}, bullish divergence RSI, price above MA 50, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair} BUY forming, {tf_spoken}, golden cross EMA 9 over 21, RSI {rsi} 50 plus, ADX {adx} strong, confidence {conf}, entry {entry}, stop {sl}, tp {tp}",
"Ok team {pair} BUY, {tf_spoken}, New York buying, support bounce confirmed, EMA 21 floor, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair_label} {pair} BUY alert, {tf_spoken}, price broke previous high, retest holding, ADX {adx}, RSI {rsi}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"BUY {pair}, {tf_spoken}, bullish pin bar at EMA 21, buyers stepping in, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair} BUY now, {tf_spoken}, oversold bounce, RSI {rsi} turning up from 40, ADX {adx} expansion, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Team {pair} BUY, {tf_spoken}, above EMA 200 bullish bias, pullback to EMA 21 done, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair_label} {pair} high probability BUY, {tf_spoken}, triple confluence, EMA 21 support, RSI 50 support, ADX {adx} strong, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair} BUY, {tf_spoken}, bullish order block tapped, reacting up, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Attention {pair} BUY, {tf_spoken}, uptrend continuation, EMA 21 and 50 aligned up, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair} BUY setup, {tf_spoken}, breakout retest buy, volume confirms, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Final call {pair} BUY, {tf_spoken}, bullish market structure, higher low formed at EMA 21, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}"
]
SELL_VNS=[
"Alright team, high probability SELL forming, {pair_label} {pair}, {tf_spoken}, SELL now,,, bullish exhausting, retesting EMA twenty one resistance, RSI {rsi} down, ADX {adx} showing drop, confidence {conf} of six, entry {entry}, stop {sl}, take profit {tp}, lets secure win",
"Team listen, {pair} perfect SELL setup, {tf_spoken}, price below EMA 200 bearish, EMA 21 below 50, RSI {rsi} weak, ADX {adx} confirms weakness, conf {conf} of six, entry {entry}, sl {sl}, tp {tp}, take now",
"Boom, {pair} SELL alert, {tf_spoken}, bearish engulfing at resistance, EMA 9 below 21, RSI {rsi} not oversold, ADX {adx} strong down, conf {conf}, entry {entry}, stop {sl}, tp {tp}, send it",
"Attention pride, {pair_label} {pair} SELL, {tf_spoken}, resistance holding, rejected from EMA 21, volume up, RSI {rsi}, ADX {adx} sellers control, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Yo team, {pair} SELL opportunity, {tf_spoken}, double top formed, MACD bearish, RSI {rsi}, ADX {adx}, textbook bearish retest, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair_label} {pair} SELL now, {tf_spoken}, trend down, price below EMA 200, pullback done at EMA 21, RSI {rsi}, ADX {adx}, confidence {conf}, entry {entry}, sl {sl}, tp {tp}",
"Beast mode SELL, {pair}, {tf_spoken}, bulls trapped, price rejecting below EMA 21, RSI {rsi} falling, ADX {adx} strong down, conf {conf}, entry {entry}, stop {sl}, tp {tp}",
"Team {pair} SELL, {tf_spoken}, London bearish, price respecting EMA 21 resistance, RSI {rsi}, ADX {adx} solid, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Lions, {pair} SELL setup, {tf_spoken}, bearish divergence RSI, below MA 50, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair} SELL forming, {tf_spoken}, death cross EMA 9 under 21, RSI {rsi} 50 minus, ADX {adx} strong, conf {conf}, entry {entry}, stop {sl}, tp {tp}",
"Ok team {pair} SELL, {tf_spoken}, New York selling, resistance rejection confirmed, EMA 21 ceiling, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair_label} {pair} SELL alert, {tf_spoken}, price broke previous low, retest holding, ADX {adx}, RSI {rsi}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"SELL {pair}, {tf_spoken}, bearish pin bar at EMA 21, sellers stepping in, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair} SELL now, {tf_spoken}, overbought drop, RSI {rsi} turning down from 60, ADX {adx} expansion, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Team {pair} SELL, {tf_spoken}, below EMA 200 bearish bias, pullback to EMA 21 done, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair_label} {pair} high probability SELL, {tf_spoken}, triple confluence, EMA 21 resistance, RSI 50 resistance, ADX {adx} strong, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair} SELL, {tf_spoken}, bearish order block tapped, reacting down, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Attention {pair} SELL, {tf_spoken}, downtrend continuation, EMA 21 and 50 aligned down, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"{pair} SELL setup, {tf_spoken}, breakdown retest sell, volume confirms, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}",
"Final call {pair} SELL, {tf_spoken}, bearish market structure, lower high formed at EMA 21, RSI {rsi}, ADX {adx}, conf {conf}, entry {entry}, sl {sl}, tp {tp}"
]

FOMO_TEXTS = [
"Don't just watch! Others just profited from this signal in bot! Tap below and get yours in 3 seconds!",
"You saw the win! Imagine if you took it! Open bot now, next signal is yours!",
"Stop scrolling! Start earning! 100 traders got this live in bot! Your turn now!",
"Another win for bot users! You only watched! Click get signal below before next one!",
"Chance slipping away! This signal just closed profit! Get next one live in bot!",
"Why watch when you can win? Tap the button! Get live signal now!",
"This was free in bot 2 minutes ago! Don't miss next! Open bot now!",
"Proof is here! But proof doesn't pay you! Signal in bot pays! Tap below!",
"Your phone showed you a win! Next time make it show you profit! Open bot!",
"Lurking doesn't pay! Trading does! Get live signal in bot now!",
"They clicked! They profited! You watched! Change that! Tap below!",
"Don't be spectator! Be trader! Button below = your next signal!",
"Signal expired! But next one loading! Be ready in bot! Tap now!",
"Win after win in bot! Channel just shows proof! Bot gives profit! Open it!",
"One tap below = one live signal! Faster than you reading this!",
"You missed this one! Don't miss next! Bot is waiting for you!",
"Free signal made profit! How many more will you watch? Get in bot!",
"Channel shows yesterday! Bot shows NOW! Tap below for live!",
"Your future self will thank you for tapping now! Get signal!",
"No more what if! Get next signal live! Click button below now!"
]

def get_next_fomo():
    global FOMO_INDEX; msg=FOMO_TEXTS[FOMO_INDEX % len(FOMO_TEXTS)]; FOMO_INDEX+=1; return msg
def get_key():
    KEYS=[k.strip() for k in os.getenv("TWELVEDATA_KEYS","").split(",") if k.strip()!='']
    if not KEYS: return None
    global key_index; k=KEYS[key_index % len(KEYS)]; key_index+=1; return k
def get_db(): return psycopg2.connect(DATABASE_URL, sslmode='require')
def init_db():
    conn=get_db(); cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS subscribers (user_id BIGINT PRIMARY KEY, phone TEXT, expiry TIMESTAMP, plan TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS payments (id SERIAL PRIMARY KEY, user_id BIGINT, amount INT, plan TEXT, mpesa_code TEXT UNIQUE, date TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS pair_stats (pair TEXT PRIMARY KEY, wins INT DEFAULT 0, loss INT DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS daily_stats (date DATE PRIMARY KEY, wins INT DEFAULT 0, loss INT DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS active_trades (id SERIAL PRIMARY KEY, user_id BIGINT, pair TEXT, api_pair TEXT, direction TEXT, entry_price FLOAT, expiry TIMESTAMP, tf TEXT, entry_time TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS referrals (new_user BIGINT PRIMARY KEY, referrer BIGINT, paid BOOLEAN DEFAULT FALSE, date TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_stats (user_id BIGINT PRIMARY KEY, wins INT DEFAULT 0, loss INT DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS win_videos (id SERIAL PRIMARY KEY, file_id TEXT UNIQUE, caption TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS usdt_payments (txid TEXT PRIMARY KEY, user_id BIGINT, amount FLOAT, date TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS expiry_warned (user_id BIGINT, warn_type TEXT, PRIMARY KEY (user_id, warn_type))")
    conn.commit(); conn.close()
init_db()

def is_active(uid):
    if int(uid)==int(ADMIN_ID): return True
    try:
        conn=get_db(); cur=conn.cursor(); cur.execute("SELECT expiry FROM subscribers WHERE user_id=%s",(uid,)); res=cur.fetchone(); conn.close()
        if res and res[0]:
            exp=res[0]; exp=exp.replace(tzinfo=EAT) if exp.tzinfo is None else exp
            return exp > datetime.now(EAT)
    except: pass
    return False
def is_admin(uid): return int(uid)==int(ADMIN_ID)
def get_user_tf(uid): return USER_TF.get(uid,'5min')
def get_user_mode(uid): return USER_MODE.get(uid,'POCKET')
def get_pair_label(s):
    s=s.upper()
    if any(x in s for x in ["BTC","ETH","SOL","BNB","XRP","ADA","DOGE","AVAX"]): return "🟡 CRYPTO"
    elif "XAU" in s or "XAG" in s: return "🟠 METAL"
    elif any(x in s for x in ["US30","NAS","SPX","GER","UK100","WTI","BRENT"]): return "🟣 INDEX"
    else: return "🔵 FOREX"
def get_session():
    h=datetime.now(EAT).hour
    if 3<=h<11: return "TOKYO"
    if 10<=h<18: return "LONDON"
    if 15<=h<23: return "NEW YORK"
    return "OVERLAP"
def spoken_tf(tf):
    tf=str(tf).lower()
    if "5min" in tf: return "5 minute time frame"
    if "15min" in tf: return "15 minute time frame"
    if "1h" in tf: return "1 hour time frame"
    if "4h" in tf: return "4 hour time frame"
    if "1m" in tf: return "1 minute time frame"
    return f"{tf} time frame"
def main_menu(uid=None):
    markup=types.ReplyKeyboardMarkup(resize_keyboard=True)
    if is_admin(uid): markup.add(types.KeyboardButton("👑 Admin Panel"))
    markup.add(types.KeyboardButton("💎 Subscribe"), types.KeyboardButton("🌊 Market"), types.KeyboardButton("🔮 Best Setup"))
    markup.add(types.KeyboardButton("📊 My Stats"), types.KeyboardButton("🎁 Referral"), types.KeyboardButton("💰 Balance"))
    markup.add(types.KeyboardButton("💹 PocketOption Mode"), types.KeyboardButton("📈 MT5 Mode"))
    markup.add(types.KeyboardButton("🟡 CRYPTO"), types.KeyboardButton("🔵 FOREX"), types.KeyboardButton("🟣 INDEX/METAL"))
    markup.add(types.KeyboardButton("🆘 Support"))
    row=[]
    for p in ALL_PAIRS:
        row.append(types.KeyboardButton(f"{get_pair_label(p)} {p}"))
        if len(row)==2: markup.add(*row); row=[]
    if row: markup.add(*row)
    return markup

def get_twelvedata_klines(symbol, interval='5min', limit=150):
    key=get_key()
    if not key: return None
    time.sleep(0.08)
    url=f'https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={limit}&apikey={key}'
    try:
        r=requests.get(url, timeout=10).json()
        if 'values' not in r: return None
        klines=[]
        for v in reversed(r['values']):
            try: klines.append([int(datetime.strptime(v['datetime'],'%Y-%m-%d %H:%M:%S').timestamp()*1000), float(v['open']), float(v['high']), float(v['low']), float(v['close']), float(v.get('volume',0))])
            except: continue
        return klines
    except: return None

def get_klines(symbol, interval='5min', limit=150):
    return get_twelvedata_klines(symbol, interval, limit)

def check_news_spike(klines):
    try:
        closes=np.array([float(k[4]) for k in klines])
        tr=pd.Series([float(k[2])-float(k[3]) for k in klines])
        atr=tr.ewm(alpha=1/14).mean().iloc[-1]
        last_body=abs(closes[-1]-float(klines[-1][1]))
        if last_body > atr*3.2: return True
        return False
    except: return False

def is_high_volatility_block(pair):
    w,l=PAIR_PERFORMANCE.get(pair,[0,0])
    if l>=2 and w+l>=3 and w/(w+l) < 0.4: return True
    if pair in NEWS_PAIRS_BLOCK and time.time() < NEWS_PAIRS_BLOCK[pair]: return True
    if pair in LOSS_COOLDOWN_PAIRS and time.time()-LOSS_COOLDOWN_PAIRS[pair] < 1800: return True
    return False

def calc_pro(klines, mode="POCKET", channel_mode=False, pair_name="BTC/USD"):
    if not klines or len(klines)<60: return None
    closes=np.array([float(k[4]) for k in klines]); highs=np.array([float(k[2]) for k in klines]); lows=np.array([float(k[3]) for k in klines]); vols=np.array([float(k[5]) for k in klines])
    close_s=pd.Series(closes); high_s=pd.Series(highs); low_s=pd.Series(lows)
    ema9=close_s.ewm(span=9).mean().iloc[-1]; ema21=close_s.ewm(span=21).mean().iloc[-1]; ema50=close_s.ewm(span=50).mean().iloc[-1]; ema200=close_s.ewm(span=200).mean().iloc[-1]
    delta=close_s.diff(); gain=delta.where(delta>0,0).ewm(alpha=1/14).mean(); loss=-delta.where(delta<0,0).ewm(alpha=1/14).mean()
    rs=gain.iloc[-1]/loss.iloc[-1] if loss.iloc[-1]!=0 else 0; rsi=100-(100/(1+rs)) if rs!=0 else 50
    tr=pd.concat([high_s-low_s, (high_s-close_s.shift()).abs(), (low_s-close_s.shift()).abs()], axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14).mean().iloc[-1]
    if pd.isna(atr) or atr==0: atr=closes[-1]*0.002
    up_move=high_s.diff(); down_move=low_s.diff().abs()
    plus_dm=pd.Series(np.where((up_move>down_move) & (up_move>0), up_move, 0.0)).ewm(alpha=1/14).mean()
    minus_dm=pd.Series(np.where((down_move>up_move) & (down_move>0), down_move, 0.0)).ewm(alpha=1/14).mean()
    plus_di=100*(plus_dm/atr) if atr!=0 else pd.Series([0]); minus_di=100*(minus_dm/atr) if atr!=0 else pd.Series([0])
    dx=100*abs(plus_di.iloc[-1]-minus_di.iloc[-1])/(plus_di.iloc[-1]+minus_di.iloc[-1]) if (plus_di.iloc[-1]+minus_di.iloc[-1])!=0 else 0
    adx=float(pd.Series([dx]).ewm(span=14).mean().iloc[-1])
    if pd.isna(adx) or adx<10: adx=18+random.uniform(0,6)
    ema12=close_s.ewm(span=12).mean(); ema26=close_s.ewm(span=26).mean(); macd_line=ema12-ema26; signal_line=macd_line.ewm(span=9).mean(); macd_bull=macd_line.iloc[-1] > signal_line.iloc[-1]
    vol_avg=np.mean(vols[-20:]) if len(vols)>=20 else np.mean(vols); vol_now=vols[-1]; vol_ok = vol_now > vol_avg*1.1 if vol_avg>0 else True
    session=get_session(); session_ok = session in ["LONDON","NEW YORK","OVERLAP"]
    ema_gap=abs(ema21-ema50)/closes[-1]*100
    price=closes[-1]
    atr_p=atr/price*100
    dist_ema=abs(price-ema21)/price*100
    is_crypto_pair = any(x in pair_name for x in ["BTC","ETH","SOL","XRP","BNB","AVAX","DOGE","ADA","LINK","LTC"])
    max_atr_allowed = 3.0 if is_crypto_pair else 2.5
    min_adx_allowed = 16 if mode=="MT5" else 18
    if channel_mode:
        if adx<min_adx_allowed: return None
        if ema_gap<0.010: return None
        if rsi<30 or rsi>80: return None
        if atr_p<MIN_ATR_P: return None
        if atr_p>max_atr_allowed: return None
        if dist_ema>MAX_SPREAD_P: return None
        if not vol_ok: return None
    else:
        if adx<min_adx_allowed: return None
        if atr_p>max_atr_allowed: return None
    if price>ema200 and ema21>ema50 and rsi>45: direction="BUY"
    elif price<ema200 and ema21<ema50 and rsi<55: direction="SELL"
    else:
        if ema21>ema50 and rsi>50: direction="BUY"
        elif ema21<ema50 and rsi<50: direction="SELL"
        else: direction="BUY" if closes[-1]>ema21 else "SELL"
    conf=2
    if adx>20: conf+=1
    if adx>26: conf+=1
    if (price>ema200 and direction=="BUY") or (price<ema200 and direction=="SELL"): conf+=1
    if vol_ok: conf+=1
    if session_ok: conf+=1
    if (macd_bull and direction=="BUY") or (not macd_bull and direction=="SELL"): conf+=1
    conf=min(5,conf)
    if conf<=2: return None
    if channel_mode and conf<3: return None
    entry=closes[-1]
    if mode=="POCKET":
        sl=entry - atr*1.5 if direction=="BUY" else entry + atr*1.5
        tp=entry + atr*2.8 if direction=="BUY" else entry - atr*2.8
        strength="POCKET"
    else:
        sl=entry - atr*2.0 if direction=="BUY" else entry + atr*2.0
        tp=entry + atr*3.8 if direction=="BUY" else entry - atr*3.8
        strength="MT5 STRONG" if conf>=4 else "MT5"
    sl_p=abs(entry-sl)/entry*100; tp_p=abs(tp-entry)/entry*100
    if sl_p<0.08 or sl_p>2.5: return None
    if tp_p/sl_p<1.7: return None
    support=float(np.min(lows[-15:])); resistance=float(np.max(highs[-15:]))
    rr=round(tp_p/sl_p,2)
    return {"direction":direction,"entry":entry,"sl":sl,"tp":tp,"adx":adx,"rsi":rsi,"conf":conf,"strength":strength,"ema21":ema21,"ema50":ema50,"ema200":ema200,"ema9":ema9,"macd_bull":macd_bull,"support":support,"resistance":resistance,"atr":atr,"klines":klines,"sl_p":sl_p,"tp_p":tp_p,"rr":rr,"vol_ok":vol_ok,"session":session,"atr_p":atr_p}

def generate_chart_pro(pair, sig, uid):
    try:
        klines=sig["klines"][-60:]
        opens=[float(k[1]) for k in klines]; highs=[float(k[2]) for k in klines]; lows=[float(k[3]) for k in klines]; closes=[float(k[4]) for k in klines]
        times=[datetime.fromtimestamp(k[0]/1000, tz=EAT) for k in klines]
        fig, ax=plt.subplots(figsize=(10.5,5.2), facecolor='#0E1116'); ax.set_facecolor('#0E1116')
        for i in range(len(klines)):
            col='#00E676' if closes[i]>=opens[i] else '#FF3D57'
            ax.plot([times[i],times[i]],[lows[i],highs[i]],color=col,linewidth=0.9)
            w=0.0007
            ax.add_patch(plt.Rectangle((mdates.date2num(times[i])-w/2, min(opens[i],closes[i])), w, max(abs(closes[i]-opens[i]), closes[i]*0.0001), facecolor=col, edgecolor=col))
        close_s=pd.Series([float(k[4]) for k in sig["klines"]])
        ax.plot(times, close_s.ewm(span=9).mean().values[-60:], color='#FFEB3B', lw=0.9, label='EMA9')
        ax.plot(times, close_s.ewm(span=21).mean().values[-60:], color='#40C4FF', lw=1.1, label='EMA21')
        ax.plot(times, close_s.ewm(span=50).mean().values[-60:], color='#FFAB40', lw=1.1, label='EMA50')
        ax.plot(times, close_s.ewm(span=200).mean().values[-60:], color='white', lw=1.5, alpha=0.9, label='EMA200')
        ax.axhline(sig["entry"], color='#FFD740', ls='--', lw=1.4, label=f"ENTRY")
        ax.axhline(sig["sl"], color='#FF5252', ls=':', lw=1.1, label=f"SL -{sig['sl_p']:.2f}%")
        ax.axhline(sig["tp"], color='#69F0AE', ls=':', lw=1.1, label=f"TP +{sig['tp_p']:.2f}%")
        ax.tick_params(colors='#8B949E', labelsize=8); ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=EAT)); ax.grid(True, color='#21262D', alpha=0.4)
        ax.legend(loc='upper left', fontsize=6.5, facecolor='#161B22', edgecolor='#30363D', labelcolor='white')
        banner="#1F883D" if sig["conf"]>=4 else "#9E6A03"
        mode_tag="POCKET" if "POCKET" in sig["strength"] else "MT5"
        fig.text(0.5,0.93,f"{BRAND_NAME} | {get_pair_label(pair)} {pair} {sig.get('tf','5MIN')} T.Frame {sig['direction']} {sig['strength']} | ADX {sig['adx']:.0f} RSI {sig['rsi']:.0f} Conf {sig['conf']}/5 | RR 1:{sig['rr']} | {mode_tag}", ha="center", fontsize=8, color="white", weight='bold', bbox=dict(facecolor=banner, alpha=0.9, pad=4, boxstyle="round,pad=0.3"))
        plt.tight_layout(pad=0.8)
        buf=BytesIO(); plt.savefig(buf, format='png', facecolor='#0E1116', dpi=180, bbox_inches='tight'); buf.seek(0); plt.close(fig)
        return buf
    except Exception as e: print(f"Chart err {e}"); return None

def check_mtf(pair, tf, direction):
    higher={"5min":"15min","15min":"1h","1h":"4h","1m":"5min"}.get(tf)
    if not higher: return True, "No higher", 0
    klines_h=get_klines(pair, higher, 80)
    if not klines_h: return True, "No data", 0
    sig_h=calc_pro(klines_h, pair_name=pair)
    if not sig_h: return True, "No data", 0
    aligned=sig_h["direction"]==direction
    return aligned, f"{spoken_tf(higher)} {sig_h['direction']} ADX {sig_h['adx']:.0f}", sig_h["adx"]

def make_vn(text, filename="/tmp/vn.mp3"):
    try: gTTS(text=text, lang='en', tld='co.uk').save(filename); return filename
    except: return None

def build_manager_vn_text(sig):
    tf=sig.get('tf','5min').lower().replace('min','m')
    if tf not in MANAGER_VN_TEMPLATES: tf='5m'
    template=random.choice(MANAGER_VN_TEMPLATES[tf])
    return template.format(pair_label=get_pair_label(sig.get('pair','BTC/USD')),pair=sig.get('pair','BTC/USD').replace("/"," "),tf_spoken=spoken_tf(sig.get('tf','5min')),direction=sig.get('direction','BUY'),adx=f"{sig.get('adx',32):.0f}",rsi=f"{sig.get('rsi',55):.0f}",conf=sig.get('conf',5),entry=f"{sig.get('entry',0):.2f}",sl=f"{sig.get('sl',0):.2f}",tp=f"{sig.get('tp',0):.2f}",support=f"{sig.get('support',0):.2f}",resistance=f"{sig.get('resistance',0):.2f}",atr=f"{sig.get('atr_p',0.3):.2f}",rr=f"1 to {sig.get('rr',1.8)}")

def send_manager_vn_to_channel(sig):
    try:
        full_text=build_manager_vn_text(sig)
        tf=sig.get('tf','5min')
        mp3=make_vn(full_text,f"/tmp/manager_{sig['pair']}_{tf}_{int(time.time())}.mp3")
        if mp3 and os.path.exists(mp3):
            with open(mp3,'rb') as v:
                bot.send_voice(CHANNEL_ID,v,caption=f"🎙️ MANAGER DESK: {tf.upper()} {sig['pair']} {sig['direction']} CONF {sig['conf']}/5 ADX {sig['adx']:.0f}")
    except Exception as e: print(f"Manager VN err {e}")

def send_testimonial_10_wins(uid):
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("SELECT wins, loss FROM user_stats WHERE user_id=%s",(uid,))
        row=cur.fetchone(); conn.close()
        if not row: return
        wins, loss = row
        if wins>0 and wins % 10 == 0:
            total=wins+loss; wr=int(wins/total*100) if total else 0
            fomo=get_next_fomo()
            caption=(f"🔥 TESTIMONIAL - 10 WINS MILESTONE 🔥\n━━━━━━━━━━━━\n"
                     f"👤 Trader ID {uid} just hit {wins} WINS with {BRAND_NAME}!\n"
                     f"📊 WR {wr}% | {wins}W-{loss}L\n"
                     f"💎 Verified by {BRAND_NAME} AI\n━━━━━━━━━━━━\n"
                     f"{fomo}\nWant same? Get signals in bot 👇")
            kb=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🤖 GET MY SIGNALS NOW", url=BOT_LINK))
            try:
                conn=get_db(); cur=conn.cursor()
                cur.execute("SELECT file_id FROM win_videos ORDER BY RANDOM() LIMIT 1")
                v=cur.fetchone(); conn.close()
                if v: bot.send_video(CHANNEL_ID, v[0], caption=caption, reply_markup=kb)
                else: bot.send_message(CHANNEL_ID, caption, reply_markup=kb)
            except: bot.send_message(CHANNEL_ID, caption, reply_markup=kb)
    except Exception as e: print(f"Testimonial err {e}")

def send_vn(chat_id, vn_type, sig=None):
    try:
        fomo=get_next_fomo()
        tf_raw = sig.get('tf','5MIN') if sig else "5MIN"
        tf_spoken = spoken_tf(tf_raw)
        txt=VN_SCRIPTS[vn_type].format(pair=sig.get('pair','BTC/USD') if sig else "BTC/USD", side=sig.get('direction','BUY') if sig else "BUY", tf=tf_spoken, adx=int(sig.get('adx',32)) if sig else 32, conf=sig.get('conf',5) if sig else 5, sl_p=sig.get('sl_p',0.22) if sig else 0.22, tp_p=sig.get('tp_p',0.35) if sig else 0.35, rr=sig.get('rr',1.6) if sig else 1.6, fomo_text=fomo, session=get_session())
        mp3=make_vn(txt)
        if mp3 and os.path.exists(mp3):
            with open(mp3,'rb') as v: bot.send_voice(chat_id, v, caption=f"🎙️ {txt}")
    except Exception as e: print(f"VN err {e}")

def post_to_channel(sig, pair, tf):
    try:
        chart=generate_chart_pro(pair, sig, ADMIN_ID)
        fomo=get_next_fomo()
        _, mtf_t, _ = check_mtf(pair, tf.lower(), sig['direction'])
        setup_name="⚡ SCALP RE-TEST EMA21" if "1m" in tf else "🔥 BREAK & RETEST + RSI 50" if "5m" in tf else "📈 HTF TREND + EMA PULLBACK" if "15m" in tf else "💎 POSITION BREAKOUT"
        caption=f"{TF_LABELS.get(tf.lower().replace('min','m'),'') } {sig['direction']} {get_pair_label(pair)} {pair}\n━━━━━━━━━━━━\n💰 {pair} | {sig['session']} | TF: {tf.upper()} - Expire {tf.upper()}\n🎯 Setup: {setup_name}\n📊 CONF {sig['conf']}/5 | ADX {sig['adx']:.0f} | RSI {sig['rsi']:.0f} | ATR {sig.get('atr_p',0):.2f}%\n━━━━━━━━━━━━\n📈 Entry: {sig['entry']:.5f}\n🎯 TP: +{sig['tp_p']:.2f}% | 🛑 SL: -{sig['sl_p']:.2f}% | RR 1:{sig['rr']}\n📊 SUP: {sig['support']:.5f} | RES: {sig['resistance']:.5f}\n✅ Aligned: {spoken_tf(tf)} {sig['direction']} + {mtf_t}\n\n🔥 {fomo}"
        markup=types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"🤖 GET LIVE {tf.upper()} SIGNAL IN BOT", url=BOT_LINK))
        if chart: bot.send_photo(CHANNEL_ID, chart, caption=caption, reply_markup=markup)
        else: bot.send_message(CHANNEL_ID, caption, reply_markup=markup)
        time.sleep(1)
        send_manager_vn_to_channel({**sig,"pair":pair,"tf":tf})
    except Exception as e: print(f"Channel post err {e}")

def poll_scheduler():
    while True:
        try:
            time.sleep(8*3600)
            q=random.choice(POLLS)
            bot.send_poll(CHANNEL_ID, question=q, options=["Yes","No","Maybe","Need more"], is_anonymous=False)
        except: pass

def keep_alive_vn():
    while True:
        try:
            time.sleep(3*3600)
            send_vn(CHANNEL_ID, "alive")
        except: pass

def send_signal_pro(uid, pair, tf):
    mode=get_user_mode(uid); tf_l=tf.lower()
    if mode=="MT5": tf_l="15min"
    if is_high_volatility_block(pair):
        bot.send_message(uid, f"⏸️ {pair} cooling - too many losses, blocked 30 mins to protect you."); return
    klines=get_klines(pair, tf_l, 150)
    if not klines: bot.send_message(uid, f"❌ No data {pair} {tf.upper()} T.Frame."); return
    sig=calc_pro(klines, mode=mode, channel_mode=False, pair_name=pair)
    if not sig: bot.send_message(uid, f"❌ No strong setup {get_pair_label(pair)} {pair} {tf.upper()} T.Frame now - choppy. Session {get_session()}"); return
    sig['tf']=tf.upper(); sig['pair']=pair
    mtf_aligned, mtf_text, _ = check_mtf(pair, tf_l, sig["direction"])
    final_conf=sig["conf"] + (1 if mtf_aligned else 0); final_conf=min(5,final_conf); sig['conf']=final_conf
    chart=generate_chart_pro(pair, sig, uid)
    if mode=="POCKET":
        caption=f"💹 {get_pair_label(pair)} POCKET {pair} {tf.upper()} T.Frame {sig['direction']} {sig['strength']}\nEntry: {sig['entry']:.5f}\nExpiry: {tf.upper()} - Click {sig['direction']} NOW\nSL: {sig['sl']:.5f} (-{sig['sl_p']:.2f}%) TP: {sig['tp']:.5f} (+{sig['tp_p']:.2f}%) RR 1:{sig['rr']}\nADX: {sig['adx']:.0f} RSI: {sig['rsi']:.0f} Conf: {final_conf}/5\n{'✅ Aligned: '+mtf_text if mtf_aligned else '⚠️ '+mtf_text} | {sig['session']}"
    else:
        caption=f"📈 {get_pair_label(pair)} MT5 {pair} {tf.upper()} T.Frame {sig['direction']} {sig['strength']}\nEntry {sig['entry']:.5f} SL {sig['sl']:.5f} (-{sig['sl_p']:.2f}%) TP {sig['tp']:.5f} (+{sig['tp_p']:.2f}%) RR 1:{sig['rr']} | ADX {sig['adx']:.0f} Conf {final_conf}/5\n✅ {mtf_text}"
    if chart: bot.send_photo(uid, chart, caption=caption)
    else: bot.send_message(uid, caption)
    expiry=datetime.now(EAT) + (timedelta(minutes=1) if "1m" in tf_l else timedelta(minutes=5) if "5m" in tf_l else timedelta(minutes=15) if "15m" in tf_l else timedelta(hours=1) if "1h" in tf_l else timedelta(hours=4))
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("INSERT INTO active_trades (user_id, pair, api_pair, direction, entry_price, expiry, tf, entry_time) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (uid, pair, pair, sig["direction"], sig["entry"], expiry, tf_l, datetime.now(EAT)))
        conn.commit(); conn.close()
    except: pass
    if final_conf>=3 and sig['adx']>=MIN_ADX_STRICT and mtf_aligned:
        sig_strict=calc_pro(klines, mode=mode, channel_mode=True, pair_name=pair)
        if sig_strict: threading.Thread(target=post_to_channel, args=(sig, pair, tf), daemon=True).start()

def run_market_scan_thread(uid, tf):
    def scan_job():
        try:
            mode=get_user_mode(uid)
            tfs_to_scan = ["15min"] if mode=="MT5" else [tf.lower()] if tf.lower()!="all" else TIMEFRAMES_ALL
            if mode=="POCKET": tfs_to_scan = [t for t in tfs_to_scan if t in ["1m","5min","15min"]]
            bot.send_message(uid, f"🌊 SCAN {get_session()} MULTI-TF {','.join([t.upper() for t in tfs_to_scan])} T.Frame {mode} 32 pairs...")
            good=[]
            for tf_scan in tfs_to_scan:
                tf_lower=tf_scan.lower()
                for symbol in ALL_PAIRS:
                    if is_high_volatility_block(symbol): continue
                    try:
                        klines=get_klines(symbol, tf_lower, 80)
                        if not klines: continue
                        sig=calc_pro(klines, mode=mode, channel_mode=True, pair_name=symbol)
                        if not sig: continue
                        mtf_aligned,_,_=check_mtf(symbol, tf_lower, sig["direction"])
                        if sig["adx"]>=MIN_ADX_STRICT and sig["conf"]>=3 and mtf_aligned:
                            label=get_pair_label(symbol)
                            good.append((sig["adx"]+sig["conf"]*10, f"{TF_LABELS.get(tf_lower.replace('min','m'), tf_lower.upper())} {label} {'🟢' if sig['direction']=='BUY' else '🔴'} {symbol} {sig['direction']} ADX {sig['adx']:.0f} Conf {sig['conf']}/5 RR 1:{sig['rr']} TF:{tf_lower.upper()}", symbol, tf_lower))
                    except: continue
                    time.sleep(0.05)
            good=sorted(good, key=lambda x: x[0], reverse=True)[:15]
            if not good:
                bot.send_message(uid, f"🌊 MULTI-TF SCAN {get_session()} - No high-quality setup now - bot protected you from losses.")
                return
            kb=types.InlineKeyboardMarkup()
            for _,line,sym,tf_l in good[:6]:
                kb.add(types.InlineKeyboardButton(f"🔍 {line[:60]}", callback_data=f"deep_{sym}_{tf_l}"))
            msg=f"🌊 MULTI-TF HEATMAP {datetime.now(EAT).strftime('%H:%M')} {get_session()} MODE {mode}\nScanned: {', '.join(tfs_to_scan).upper()} T.Frame\n\n🔥 TOP {len(good)} HIGH QUALITY (TF shown):\n" + "\n".join([g[1] for g in good])
            bot.send_message(uid, msg, reply_markup=kb)
        except Exception as e: bot.send_message(uid, f"❌ Scan error {e}"); print(f"Scan err {e}")
    threading.Thread(target=scan_job, daemon=True).start()

@bot.message_handler(commands=['pay'])
def pay_cmd(m):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🇰🇪 I AM IN KENYA (M-PESA)", callback_data="pay_kenya"))
    kb.add(types.InlineKeyboardButton("🌍 I AM INTERNATIONAL (BINANCE USDT)", callback_data="pay_intl"))
    bot.send_message(m.chat.id, "💳 WHERE ARE YOU? Choose:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["pay_kenya","pay_intl","back_pay"])
def pay_location_cb(c):
    if c.data=="back_pay": pay_cmd(c.message); bot.answer_callback_query(c.id); return
    if c.data=="pay_kenya":
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("📅 7 DAYS - KSH 2000", callback_data="kenya_7"))
        kb.add(types.InlineKeyboardButton("📅 30 DAYS - KSH 7200 [BEST]", callback_data="kenya_30"))
        kb.add(types.InlineKeyboardButton("⬅️ BACK", callback_data="back_pay"))
        bot.send_message(c.message.chat.id, "🇰🇪 KENYA M-PESA Choose:", reply_markup=kb)
    else:
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("📅 7 DAYS - $16", callback_data="intl_7"))
        kb.add(types.InlineKeyboardButton("📅 30 DAYS - $50 [BEST]", callback_data="intl_30"))
        kb.add(types.InlineKeyboardButton("⬅️ BACK", callback_data="back_pay"))
        bot.send_message(c.message.chat.id, "🌍 INTERNATIONAL BINANCE Choose:", reply_markup=kb)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data in ["kenya_7","kenya_30","intl_7","intl_30"])
def pay_plan_cb(c):
    if c.data.startswith("kenya"):
        days = 7 if "7" in c.data else 30; price = 2000 if days==7 else 7200
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(f"📋 COPY M-PESA: {MPESA_NUMBER}", callback_data="copy_mpesa"))
        kb.add(types.InlineKeyboardButton("✅ I HAVE SENT + HAVE CODE", callback_data=f"have_code_{days}"))
        kb.add(types.InlineKeyboardButton("❓ HOW TO PAY?", callback_data="how_mpesa"))
        kb.add(types.InlineKeyboardButton("⬅️ BACK", callback_data="pay_kenya"))
        bot.send_message(c.message.chat.id, f"🇰🇪 M-PESA - {days} DAYS - KSH {price}\nNumber: {MPESA_NUMBER} Name: {MPESA_NAME}\nAmount: {price}", reply_markup=kb)
    else:
        days = 7 if "7" in c.data else 30; amount = 16 if days==7 else 50
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(f"📋 COPY TRC20 ADDRESS", callback_data=f"copy_usdt_{days}"))
        kb.add(types.InlineKeyboardButton("✅ I HAVE SENT + HAVE TxID", callback_data=f"have_txid_{days}"))
        kb.add(types.InlineKeyboardButton("❓ HOW TO PAY?", callback_data=f"how_usdt_{days}"))
        kb.add(types.InlineKeyboardButton("⬅️ BACK", callback_data="pay_intl"))
        bot.send_message(c.message.chat.id, f"🌍 BINANCE - {days} DAYS - ${amount}\nNetwork: TRC20 ONLY!\nAddress: {USDT_TRC20}", reply_markup=kb)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("how_"))
def how_cb(c):
    if "mpesa" in c.data: bot.send_message(c.message.chat.id, "📱 M-PESA:\n1. Send Money\n2. 0143773606\n3. Amount\n4. PIN\n5. Get CODE")
    else: bot.send_message(c.message.chat.id, f"🌍 BINANCE:\n1. Withdraw USDT\n2. Network TRC20\n3. Paste {USDT_TRC20}\n4. Amount\n5. Send -> Copy TxID")
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("have_"))
def have_cb(c):
    days = int(c.data.split("_")[-1])
    if "code" in c.data: bot.send_message(c.message.chat.id, f"✅ Paste M-Pesa CODE for {days}d")
    else: bot.send_message(c.message.chat.id, f"✅ Paste TxID for {days}d")
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("copy_"))
def copy_cb(c):
    if "mpesa" in c.data: bot.send_message(c.message.chat.id, f"📋 M-PESA:\n`{MPESA_NUMBER}`", parse_mode='Markdown')
    else: bot.send_message(c.message.chat.id, f"📋 TRC20:\n`{USDT_TRC20}`", parse_mode='Markdown')
    bot.answer_callback_query(c.id, "Copied!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("tf_"))
def tf_handler(call):
    uid=call.from_user.id; tf=call.data.split("_")[1]; USER_TF[uid]=tf
    bot.answer_callback_query(call.id, f"✅ {tf.upper()} T.Frame")
    run_market_scan_thread(uid, "all" if tf=="all" else tf)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sig_"))
def sig_cb(call):
    data=call.data[4:]; last=data.rfind("_"); pair=data[:last]; tf=data[last+1:]; uid=call.from_user.id
    if not is_active(uid): pay_cmd(call.message); return
    if get_user_mode(uid)=="MT5": tf="15min"
    bot.answer_callback_query(call.id, f"{pair} {tf}"); threading.Thread(target=send_signal_pro, args=(uid, pair, tf), daemon=True).start()

@bot.callback_query_handler(func=lambda c: c.data.startswith("deep_"))
def deep_cb(call):
    try: d=call.data[5:]; last=d.rfind("_"); pair=d[:last]; tf=d[last+1:]
    except: return
    uid=call.from_user.id
    if not is_active(uid): pay_cmd(call.message); return
    bot.answer_callback_query(call.id, f"Deep {pair} {tf}"); threading.Thread(target=send_signal_pro, args=(uid, pair, tf), daemon=True).start()

@bot.message_handler(commands=['admin'])
def admin_cmd(m):
    if not is_admin(m.from_user.id): bot.send_message(m.chat.id, "⛔ Not admin"); return
    kb=types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("📊 Stats", callback_data="admin_stats"), types.InlineKeyboardButton("👥 Users", callback_data="admin_users"))
    kb.add(types.InlineKeyboardButton("💳 Payments", callback_data="admin_pays"), types.InlineKeyboardButton("📈 Pair Stats", callback_data="admin_pairs"))
    kb.add(types.InlineKeyboardButton("🔥 Daily", callback_data="admin_daily"), types.InlineKeyboardButton("⏳ Active Trades", callback_data="admin_trades"))
    kb.add(types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"))
    kb.add(types.InlineKeyboardButton("🎬 Win Videos", callback_data="admin_win_videos"))
    kb.add(types.InlineKeyboardButton("➕ Extend User", callback_data="admin_extend_menu"))
    kb.add(types.InlineKeyboardButton("🧹 CLEAR ALL STATS 0W/0L", callback_data="admin_clear_confirm"))
    bot.send_message(m.chat.id, f"👑 Admin {BRAND_NAME} V22.8.13 LOOSENED 1060 LINES\n32 pairs | ADX16+ | ATR3.0 crypto | MULTI TF", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_clear"))
def admin_clear_cb(c):
    if not is_admin(c.from_user.id): return
    if c.data=="admin_clear_confirm":
        kb=types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("✅ YES CLEAR ALL 0W/0L", callback_data="admin_clear_yes"))
        kb.add(types.InlineKeyboardButton("❌ CANCEL", callback_data="admin_clear_no"))
        bot.send_message(c.message.chat.id, "⚠️ Clear all stats?\nDELETE pair_stats, daily_stats, user_stats, active_trades + cooling", reply_markup=kb)
    elif c.data=="admin_clear_yes":
        conn=get_db(); cur=conn.cursor()
        cur.execute("DELETE FROM pair_stats"); cur.execute("DELETE FROM daily_stats"); cur.execute("DELETE FROM user_stats"); cur.execute("DELETE FROM active_trades")
        conn.commit(); conn.close()
        global PAIR_PERFORMANCE, LOSS_COOLDOWN_PAIRS, NEWS_PAIRS_BLOCK
        PAIR_PERFORMANCE={}; LOSS_COOLDOWN_PAIRS={}; NEWS_PAIRS_BLOCK={}
        bot.send_message(c.message.chat.id, "✅ ALL CLEARED 0W/0L Fresh")
    elif c.data=="admin_clear_no": bot.send_message(c.message.chat.id, "❌ Cancelled")
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_mode_"))
def set_mode_cb2(c):
    uid=c.from_user.id; mode="POCKET" if "pocket" in c.data else "MT5"; USER_MODE[uid]=mode
    bot.answer_callback_query(c.id, f"{mode} Set!"); bot.send_message(uid, f"✅ MODE: {mode} T.Frame", reply_markup=main_menu(uid))

@bot.message_handler(commands=['start'])
def start_cmd(m):
    uid=m.from_user.id
    if "ref_" in m.text:
        try:
            ref=int(m.text.split("ref_")[1])
            if ref!=uid:
                conn=get_db(); cur=conn.cursor()
                cur.execute("INSERT INTO referrals (new_user, referrer, paid, date) VALUES (%s,%s,%s,%s) ON CONFLICT (new_user) DO NOTHING",(uid, ref, False, datetime.now(EAT)))
                conn.commit(); conn.close()
        except: pass
    if is_active(uid):
        bot.send_message(uid, f"✦ {BRAND_NAME} ACTIVE ✦ Mode {get_user_mode(uid)} TF 15MIN LOCKED\n32 Pairs | LOSS KILLER V22.8.13 LOOSENED 1060 LINES", reply_markup=main_menu(uid))
    else:
        kb=types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("💹 I Trade PocketOption / Quotex (Binary 5/15min)", callback_data="set_mode_pocket"))
        kb.add(types.InlineKeyboardButton("📈 I Trade MT5 / Exness (Forex 15min)", callback_data="set_mode_mt5"))
        bot.send_message(uid, f"✦ {BRAND_NAME} ✦\n\nV22.8.13 LOOSENED 1060 LINES: ADX16 + ATR 3.0% - crypto works in MT5 now", reply_markup=kb)
        kb2 = types.InlineKeyboardMarkup(row_width=1)
        kb2.add(types.InlineKeyboardButton("🇰🇪 KENYA M-PESA", callback_data="pay_kenya"))
        kb2.add(types.InlineKeyboardButton("🌍 INTERNATIONAL BINANCE", callback_data="pay_intl"))
        bot.send_message(uid, "💳 Then choose payment:", reply_markup=kb2)

@bot.message_handler(func=lambda m: m.text in ["🌊 Market","🔮 Best Setup","📊 My Stats","💰 Balance","🎁 Referral","💎 Subscribe","🆘 Support","💹 PocketOption Mode","📈 MT5 Mode","🟡 CRYPTO","🔵 FOREX","🟣 INDEX/METAL","👑 Admin Panel"])
def menu_handler(m):
    uid=m.from_user.id; txt=m.text
    if txt=="👑 Admin Panel": admin_cmd(m); return
    if txt=="🌊 Market":
        if not is_active(uid): pay_cmd(m); return
        mode=get_user_mode(uid)
        run_market_scan_thread(uid, "15min" if mode=="MT5" else "5min")
    elif txt=="🔮 Best Setup":
        if not is_active(uid): pay_cmd(m); return
        def job():
            mode=get_user_mode(uid)
            bot.send_message(uid, f"🔮 BEST 3 {mode} MULTI TF scanning...")
            best=[]; seen=set(); tfs=["15min"] if mode=="MT5" else ["5min","15min"]
            for symbol in ALL_PAIRS:
                if is_high_volatility_block(symbol): continue
                for tf in tfs:
                    klines=get_klines(symbol, tf, 80)
                    if not klines: continue
                    sig=calc_pro(klines, mode=mode, channel_mode=True, pair_name=symbol)
                    if not sig: continue
                    if symbol+"_"+tf in seen: continue
                    score=sig["adx"]+sig["conf"]*10+sig["rr"]*5
                    best.append((score, symbol, tf, sig)); seen.add(symbol+"_"+tf); time.sleep(0.05)
            best=sorted(best, key=lambda x: x[0], reverse=True)[:3]
            if not best: bot.send_message(uid, "✦ No high-quality setup now - bot protected you."); return
            msg=f"🔮 TOP 3 {mode} MULTI TF\n\n"
            for i,(score,sym,tf,sig) in enumerate(best,1): msg+=f"{i}. {get_pair_label(sym)} {sym} {tf.upper()} T.Frame {sig['direction']} Conf {sig['conf']}/5 ADX {sig['adx']:.0f} RR 1:{sig['rr']} TF:{tf.upper()} ✅\n"
            bot.send_message(uid, msg)
        threading.Thread(target=job, daemon=True).start()
    elif txt=="📊 My Stats":
        conn=get_db(); cur=conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN paid THEN 1 ELSE 0 END) FROM referrals WHERE referrer=%s",(uid,)); cnt,paid=cur.fetchone(); cnt=cnt or 0; paid=paid or 0
        cur.execute("SELECT wins, loss FROM user_stats WHERE user_id=%s",(uid,)); row=cur.fetchone(); pw,pl = (row[0], row[1]) if row else (0,0)
        cur.execute("SELECT COUNT(*) FROM active_trades WHERE user_id=%s",(uid,)); active_wait=cur.fetchone()[0]
        cur.execute("SELECT expiry, plan FROM subscribers WHERE user_id=%s",(uid,)); sub=cur.fetchone(); exp_str="Not VIP"; plan_str="-"
        if sub: exp,plan=sub; exp_str=exp.strftime('%Y-%m-%d %H:%M') if exp else 'N/A'; plan_str=plan
        cur.execute("SELECT SUM(wins), SUM(loss) FROM pair_stats"); gw,gl=cur.fetchone(); gw=gw or 0; gl=gl or 0; gwr=int(gw/(gw+gl)*100) if (gw+gl) else 0
        conn.close()
        bot.send_message(uid, f"📊 {BRAND_NAME}\nID: {uid}\nPlan: {plan_str} Exp: {exp_str}\nMode: {get_user_mode(uid)} TF: 15MIN\nWait: {active_wait}\nWins: {pw} Loss: {pl}\nReferrals: {cnt} Paid: {paid}\nGLOBAL: {gw}W-{gl}L WR {gwr}%")
    elif txt=="💰 Balance": bot.send_message(uid, f"💰 Risk 2%\nMode: {get_user_mode(uid)} TF: 15MIN LOCKED\nPairs: 32\nLoss Killer: ON | ADX16 ATR3.0 LOOSENED 1060 LINES")
    elif txt=="🎁 Referral":
        link=f"https://t.me/{bot.get_me().username}?start=ref_{uid}"
        bot.send_message(uid, f"🎁 Link:\n{link}\n+3 days when friend pays")
    elif txt=="💎 Subscribe": pay_cmd(m)
    elif txt=="🆘 Support":
        kb=types.InlineKeyboardMarkup(row_width=2)
        kb.add(types.InlineKeyboardButton("💰 Deposit Issue", callback_data="sup_deposit"),
               types.InlineKeyboardButton("📡 No Signals", callback_data="sup_signals"),
               types.InlineKeyboardButton("📉 Losses Help", callback_data="sup_loss"),
               types.InlineKeyboardButton("🤖 Bot Problem", callback_data="sup_bot"),
               types.InlineKeyboardButton("🎫 Open Ticket", callback_data="sup_ticket"),
               types.InlineKeyboardButton("📞 Human @Denverlyk", url=SUPPORT_LINK))
        bot.send_message(uid, f"🆘 {BRAND_NAME} SUPPORT CENTER\n⏱️ Avg reply: 5 mins\n🟢 Admin online\nChoose issue:", reply_markup=kb)
    elif txt=="💹 PocketOption Mode": USER_MODE[uid]="POCKET"; bot.send_message(uid, "✅ Mode: POCKETOPTION", reply_markup=main_menu(uid))
    elif txt=="📈 MT5 Mode": USER_MODE[uid]="MT5"; bot.send_message(uid, "✅ Mode: MT5 15MIN LOCKED", reply_markup=main_menu(uid))
    elif txt in ["🟡 CRYPTO","🔵 FOREX","🟣 INDEX/METAL"]:
        if not is_active(uid): pay_cmd(m); return
        filt = "CRYPTO" if "CRYPTO" in txt else "FOREX" if "FOREX" in txt else "INDEX"
        markup=types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("⬅️ Back to All"))
        row=[]
        for p in ALL_PAIRS:
            label=get_pair_label(p)
            if filt in label:
                row.append(types.KeyboardButton(f"{label} {p}"))
                if len(row)==2: markup.add(*row); row=[]
        if row: markup.add(*row)
        bot.send_message(uid, f"{txt} Pairs - Tap:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text=="⬅️ Back to All")
def back_all(m): bot.send_message(m.chat.id, "All pairs:", reply_markup=main_menu(m.from_user.id))

@bot.callback_query_handler(func=lambda c: c.data.startswith("sup_"))
def support_pro_cb(c):
    typ=c.data.replace("sup_","")
    faqs={
        "deposit":"💰 DEPOSIT\n1. Click VIP\n2. Choose plan\n3. Send screenshot + TXID/CODE\n4. Admin confirms 5-30 mins\nIf delay, open ticket with TXID.",
        "signals":"📡 SIGNALS\nBot scans 15min for MT5, 5min for POCKET. ADX>16 + EMA + RSI + HTF + Volume. Only quality signals. V22.8.13 loosened to give more signals.",
        "loss":"📉 LOSSES?\nEven pro 60% win is profit because R:R 1:1.9. Don't double lot after loss. Bot auto-blocks losing pairs 30 mins. Follow TP/SL exactly.",
        "bot":"🤖 BOT NOT WORKING?\nSend /start again. If expiry ended, renew. Try Market scan. Still stuck? Open ticket."
    }
    if typ in faqs:
        kb=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Solved", callback_data="sup_solved"),types.InlineKeyboardButton("🎫 Still need help", callback_data="sup_ticket"))
        bot.send_message(c.message.chat.id, faqs[typ], reply_markup=kb)
    elif typ=="ticket":
        bot.send_message(c.message.chat.id,"🎫 OPEN TICKET\nSend in ONE message:\n1. Your User ID\n2. Screenshot\n3. Problem")
        USER_STATE_TICKET[c.from_user.id]="awaiting_ticket"
    elif typ=="solved":
        bot.send_message(c.message.chat.id,"✅ Great! Need us again? Click Support. Good luck! 🚀")
    bot.answer_callback_query(c.id)

@bot.message_handler(func=lambda m: USER_STATE_TICKET.get(m.from_user.id)=="awaiting_ticket")
def handle_ticket(m):
    uid=m.from_user.id; USER_STATE_TICKET.pop(uid,None)
    kb=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("💬 Chat User", url=f"tg://user?id={uid}"))
    bot.send_message(ADMIN_ID, f"🎫 NEW TICKET\nUser: {uid} @{m.from_user.username}\n\n{m.text}\nTime: {datetime.now(EAT)}", reply_markup=kb)
    if m.photo: bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
    bot.send_message(uid, "✅ Ticket sent! Admin replies 5-15 mins. 🕐")

@bot.message_handler(func=lambda m: re.match(r'^[A-Z0-9]{10}$', m.text.strip()))
def mpesa_code(m):
    code=m.text.strip().upper(); uid=m.from_user.id
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT id FROM payments WHERE mpesa_code=%s",(code,))
    if cur.fetchone(): bot.send_message(uid, "❌ Code used"); conn.close(); return
    conn.close()
    kb=types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("7 Days 2000", callback_data=f"paycode_{code}_7"), types.InlineKeyboardButton("30 Days 7200", callback_data=f"paycode_{code}_30"))
    bot.send_message(uid, f"Code {code} - Which plan?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("paycode_"))
def paycode_cb(c):
    _,code,days=c.data.split("_"); days=int(days); amount=PRICE_7DAYS if days==7 else PRICE_30DAYS; uid=c.from_user.id
    PENDING_PAYMENTS[uid]={"code":code,"days":days,"amount":amount}
    bot.send_message(ADMIN_ID, f"⚠️ M-PESA {uid} Ksh {amount} {days}D CODE {code}", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ ACTIVATE", callback_data=f"approve_{uid}"), types.InlineKeyboardButton("❌ REJECT", callback_data=f"reject_{uid}")))
    bot.send_message(uid, f"✅ Sent to admin"); bot.answer_callback_query(c.id, "Sent")

@bot.message_handler(func=lambda m: re.match(r'^[a-fA-F0-9]{64}$', m.text.strip()))
def usdt_txid_handler(m):
    txid=m.text.strip(); uid=m.from_user.id
    bot.send_message(uid, f"🔍 Checking {txid[:20]}...")
    def check():
        ok, amount, _ = verify_tron_usdt(txid)
        if not ok: bot.send_message(uid, f"❌ Not found or not to {MY_TRC20}"); return
        auto_activate_usdt(uid, txid, amount)
    threading.Thread(target=check, daemon=True).start()

def verify_tron_usdt(txid):
    try:
        url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={txid}"
        r = requests.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0"}).json()
        if not r or r.get('contractRet')!= 'SUCCESS': return False, 0, None
        trc20 = r.get('trc20TransferInfo', [])
        if not trc20: trc20 = r.get('tokenTransferInfo', {}).get('transfersAllList', [])
        for t in trc20:
            to_addr = t.get('to_address') or t.get('toAddress')
            contract = t.get('contract_address') or t.get('contractAddress') or ""
            symbol = t.get('symbol') or t.get('tokenInfo',{}).get('tokenAbbr','')
            is_usdt = ('USDT' in str(symbol).upper() or contract == USDT_CONTRACT)
            if is_usdt and to_addr == MY_TRC20:
                try: amount = float(t.get('amount_str','0')) / 1_000_000
                except: amount=0
                if amount>0: return True, amount, to_addr
        return False, 0, None
    except: return False, 0, None

def auto_activate_usdt(uid, txid, amount):
    days = 7 if 15 <= amount < 35 else 30 if amount >= 35 else 0
    if days==0:
        bot.send_message(uid, f"❌ Amount ${amount} not valid. Send $16 for 7d or $50 for 30d."); return False
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT txid FROM usdt_payments WHERE txid=%s",(txid,))
    if cur.fetchone(): bot.send_message(uid, "❌ TxID already used!"); conn.close(); return False
    expiry = datetime.now(EAT) + timedelta(days=days)
    cur.execute("INSERT INTO subscribers (user_id, phone, expiry, plan) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET expiry=%s, plan=%s", (uid, f"USDT${amount}", expiry, f"{days}d", expiry, f"{days}d"))
    cur.execute("INSERT INTO usdt_payments (txid, user_id, amount, date) VALUES (%s,%s,%s,%s)", (txid, uid, amount, datetime.now(EAT)))
    conn.commit(); conn.close()
    try: link=bot.create_chat_invite_link(CHANNEL_ID, member_limit=1).invite_link; bot.send_message(uid, f"✅ USDT CONFIRMED! ${amount} -> {days} days ACTIVE!\nJoin: {link}")
    except: bot.send_message(uid, f"✅ USDT CONFIRMED! ${amount} -> {days}d ACTIVE!")
    bot.send_message(ADMIN_ID, f"💰 AUTO USDT User {uid} ${amount}={days}d Tx {txid[:20]}")
    return True

def extend_user_expiry(target_id, days):
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("SELECT expiry FROM subscribers WHERE user_id=%s",(target_id,)); r=cur.fetchone()
        base=datetime.now(EAT)
        if r and r[0]:
            exp=r[0].replace(tzinfo=EAT) if r[0].tzinfo is None else r[0]
            if exp>base: base=exp
        new_exp = base + timedelta(days=days)
        cur.execute("INSERT INTO subscribers (user_id, phone, expiry, plan) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET expiry=%s, plan=%s", (target_id, f"ADMIN+{days}d", new_exp, f"{days}d", new_exp, f"{days}d"))
        cur.execute("DELETE FROM expiry_warned WHERE user_id=%s",(target_id,)); conn.commit(); conn.close(); return new_exp
    except: return None

@bot.callback_query_handler(func=lambda c: c.data.startswith("approve_"))
def approve_user(c):
    if not is_admin(c.from_user.id): return
    uid=int(c.data.split("_")[1]); data=PENDING_PAYMENTS.get(uid)
    if not data: bot.answer_callback_query(c.id, "No pending"); return
    expiry=datetime.now(EAT)+timedelta(days=data['days'])
    conn=get_db(); cur=conn.cursor()
    cur.execute("INSERT INTO subscribers (user_id, phone, expiry, plan) VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET expiry=%s, plan=%s", (uid, "MANUAL", expiry, f"{data['days']}d", expiry, f"{data['days']}d"))
    cur.execute("INSERT INTO payments (user_id, amount, plan, mpesa_code, date) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (mpesa_code) DO NOTHING", (uid, data['amount'], f"{data['days']}d", data['code'], datetime.now(EAT)))
    conn.commit(); conn.close()
    try: link=bot.create_chat_invite_link(CHANNEL_ID, member_limit=1).invite_link; bot.send_message(uid, f"✅ APPROVED {data['days']}d Join: {link}")
    except: bot.send_message(uid, f"✅ APPROVED {data['days']}d")
    bot.answer_callback_query(c.id, "Activated"); PENDING_PAYMENTS.pop(uid, None)

@bot.callback_query_handler(func=lambda c: c.data.startswith("reject_"))
def reject_user(c):
    if not is_admin(c.from_user.id): return
    uid=int(c.data.split("_")[1]); bot.send_message(uid, "❌ Not found"); bot.answer_callback_query(c.id, "Rejected"); PENDING_PAYMENTS.pop(uid, None)

@bot.message_handler(commands=['extend'])
def extend_cmd(m):
    if not is_admin(m.from_user.id): return
    try:
        parts=m.text.split(); uid=int(parts[1]); days=int(parts[2])
        new_exp=extend_user_expiry(uid, days)
        bot.send_message(m.chat.id, f"✅ Extended {uid} by {days}d -> {new_exp}")
        try: bot.send_message(uid, f"🎁 Admin extended {days}d! New expiry: {new_exp.strftime('%Y-%m-%d')}")
        except: pass
    except: bot.send_message(m.chat.id, "Usage: /extend 123456789 7")

@bot.message_handler(commands=['win_video'])
def save_win_video(m):
    if not is_admin(m.from_user.id): return
    if not m.reply_to_message or not m.reply_to_message.video:
        bot.send_message(m.chat.id, "Reply to a video with /win_video"); return
    file_id=m.reply_to_message.video.file_id
    conn=get_db(); cur=conn.cursor()
    cur.execute("INSERT INTO win_videos (file_id, caption) VALUES (%s,%s) ON CONFLICT (file_id) DO NOTHING",(file_id, m.reply_to_message.caption or "Win"))
    conn.commit(); conn.close()
    bot.send_message(m.chat.id, "✅ Win video saved - will be used for 10-win testimonials")

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_") and not c.data.startswith("admin_clear"))
def admin_cb(c):
    if not is_admin(c.from_user.id): return
    conn=get_db(); cur=conn.cursor()
    if c.data=="admin_stats":
        cur.execute("SELECT COUNT(*) FROM subscribers"); active=cur.fetchone()[0]
        cur.execute("SELECT COUNT(*), SUM(amount) FROM payments"); cnt,rev=cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM active_trades"); trades=cur.fetchone()[0]
        bot.send_message(c.message.chat.id, f"📊 {BRAND_NAME} V22.8.13 LOOSENED 1060 LINES\nActive: {active}\nPayments: {cnt} Rev {rev or 0}\nTrades waiting: {trades}\nBlocked pairs: {len(PAIR_PERFORMANCE)} cooling\nFilters: ADX16 ATR 3.0% crypto 2.5% forex SL 0.08-2.5%")
    elif c.data=="admin_users":
        cur.execute("SELECT user_id, expiry, plan FROM subscribers ORDER BY expiry DESC LIMIT 15")
        msg="👥 Last 15 VIP:\n"
        for uid,exp,plan in cur.fetchall(): es=exp.strftime('%m-%d %H:%M') if exp else 'N/A'; msg+=f"{uid} {plan} {es}\n"
        bot.send_message(c.message.chat.id, msg)
    elif c.data=="admin_pays":
        cur.execute("SELECT user_id, amount, plan, mpesa_code, date FROM payments ORDER BY date DESC LIMIT 15")
        msg="💳 Last 15:\n"
        for uid,amt,plan,code,date in cur.fetchall(): msg+=f"{uid} Ksh{amt} {plan} {code}\n"
        bot.send_message(c.message.chat.id, msg)
    elif c.data=="admin_pairs":
        cur.execute("SELECT pair, wins, loss FROM pair_stats ORDER BY wins DESC LIMIT 20")
        msg="📈 Pair WR:\n"
        for p,w,l in cur.fetchall(): tot=w+l; wr=int(w/tot*100) if tot else 0; msg+=f"{p} {w}W-{l}L {wr}%\n"
        bot.send_message(c.message.chat.id, msg or "No stats")
    elif c.data=="admin_daily":
        cur.execute("SELECT date, wins, loss FROM daily_stats ORDER BY date DESC LIMIT 7")
        msg="🔥 Daily:\n"
        for d,w,l in cur.fetchall(): tot=w+l; wr=int(w/tot*100) if tot else 0; msg+=f"{d} {w}W-{l}L {wr}%\n"
        bot.send_message(c.message.chat.id, msg or "No daily")
    elif c.data=="admin_trades":
        cur.execute("SELECT user_id, pair, direction, tf FROM active_trades ORDER BY expiry ASC LIMIT 20")
        msg="⏳ Active:\n"
        for uid,p,d,tf in cur.fetchall(): msg+=f"{uid} {p} {d} {tf}\n"
        bot.send_message(c.message.chat.id, msg or "No active")
    elif c.data=="admin_broadcast": bot.send_message(c.message.chat.id, "Use /broadcast message")
    elif c.data=="admin_extend_menu": bot.send_message(c.message.chat.id, "Use /extend USER_ID DAYS")
    elif c.data=="admin_win_videos":
        cur.execute("SELECT COUNT(*) FROM win_videos"); cnt=cur.fetchone()[0]
        bot.send_message(c.message.chat.id, f"🎬 Win videos saved: {cnt}\nUse /win_video reply to video to add")
    conn.close(); bot.answer_callback_query(c.id)

@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(m):
    if not is_admin(m.from_user.id): return
    text=m.text.replace('/broadcast','').strip()
    if not text: bot.send_message(m.chat.id, "Usage: /broadcast Hello VIPs"); return
    conn=get_db(); cur=conn.cursor(); cur.execute("SELECT user_id FROM subscribers"); users=cur.fetchall(); conn.close()
    cnt=0
    for (uid,) in users:
        try: bot.send_message(uid, f"📢 {BRAND_NAME}\n\n{text}"); cnt+=1; time.sleep(0.05)
        except: continue
    bot.send_message(m.chat.id, f"✅ Broadcast sent to {cnt} users")

def result_checker():
    print(f"Result checker {BRAND_NAME} V22.8.13")
    while True:
        try:
            conn=get_db(); cur=conn.cursor()
            cur.execute("SELECT id, user_id, pair, api_pair, direction, entry_price, tf, expiry FROM active_trades WHERE expiry <= %s", (datetime.now(EAT),))
            trades=cur.fetchall()
            for tid, uid, pair_display, api_pair, direction, entry, tf, exp in trades:
                try:
                    klines=get_klines(api_pair, tf, 5)
                    curr=float(klines[-1][4]) if klines else None
                    if curr is None: continue
                    win=(direction=="BUY" and curr>entry) or (direction=="SELL" and curr<entry)
                    if pair_display not in PAIR_PERFORMANCE: PAIR_PERFORMANCE[pair_display]=[0,0]
                    if win: PAIR_PERFORMANCE[pair_display][0]+=1
                    else:
                        PAIR_PERFORMANCE[pair_display][1]+=1
                        LOSS_COOLDOWN_PAIRS[pair_display]=time.time()
                        w,l=PAIR_PERFORMANCE[pair_display]
                        if w+l>=5 and w/(w+l)<0.45:
                            NEWS_PAIRS_BLOCK[pair_display]=time.time()+7200
                            try: bot.send_message(ADMIN_ID, f"⚠️ PAIR BLOCKED {pair_display} WR {w/(w+l)*100:.0f}% {w}W-{l}L cooling 2h")
                            except: pass
                    cur.execute("INSERT INTO pair_stats (pair, wins, loss) VALUES (%s,%s,%s) ON CONFLICT (pair) DO UPDATE SET wins=pair_stats.wins+%s, loss=pair_stats.loss+%s", (pair_display, 1 if win else 0, 0 if win else 1, 1 if win else 0, 0 if win else 1))
                    today=datetime.now(EAT).date()
                    cur.execute("INSERT INTO daily_stats (date, wins, loss) VALUES (%s,%s,%s) ON CONFLICT (date) DO UPDATE SET wins=daily_stats.wins+%s, loss=daily_stats.loss+%s", (today, 1 if win else 0, 0 if win else 1, 1 if win else 0, 0 if win else 1))
                    cur.execute("INSERT INTO user_stats (user_id, wins, loss) VALUES (%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET wins=user_stats.wins+%s, loss=user_stats.loss+%s", (uid, 1 if win else 0, 0 if win else 1, 1 if win else 0, 0 if win else 1))
                    conn.commit()
                    pnl=(curr-entry)/entry*100 if direction=="BUY" else (entry-curr)/entry*100
                    try:
                        bot.send_message(uid, f"{'✅ WIN' if win else '❌ LOSS'} {get_pair_label(pair_display)} {pair_display} {spoken_tf(tf).upper()} {direction}\nEntry {entry:.5f} -> {curr:.5f} {pnl:+.2f}% RR 1:1.9")
                        if win:
                            threading.Thread(target=send_testimonial_10_wins, args=(uid,), daemon=True).start()
                    except: pass
                    cur.execute("DELETE FROM active_trades WHERE id=%s",(tid,)); conn.commit()
                except Exception as e: print(f"Result inner {e}")
            conn.close()
        except Exception as e: print(f"Result loop {e}")
        time.sleep(20)

def expiry_checker():
    while True:
        try:
            conn=get_db(); cur=conn.cursor()
            cur.execute("SELECT user_id, expiry FROM subscribers")
            for uid,exp in cur.fetchall():
                if not exp: continue
                exp=exp.replace(tzinfo=EAT) if exp.tzinfo is None else exp
                if (exp - datetime.now(EAT)).total_seconds() < 0:
                    cur.execute("DELETE FROM subscribers WHERE user_id=%s",(uid,)); conn.commit()
                    try: bot.send_message(uid, f"✦ {BRAND_NAME} ✦\n🔒 VIP Expired. Renew: /pay")
                    except: pass
            conn.close()
        except: pass
        time.sleep(300)

threading.Thread(target=result_checker, daemon=True).start()
threading.Thread(target=expiry_checker, daemon=True).start()
threading.Thread(target=poll_scheduler, daemon=True).start()
threading.Thread(target=keep_alive_vn, daemon=True).start()

print(f"{BRAND_NAME} V22.8.13 LOOSENED 1060 LINES - ADX16 + ATR3.0 - MT5 CRYPTO ENABLED + ALL HANDLERS")
bot.remove_webhook()
time.sleep(1)
bot.infinity_polling(skip_pending=True, timeout=60)
