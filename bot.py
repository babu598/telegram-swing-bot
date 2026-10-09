import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import yfinance as yf
import pandas as pd
import google.generativeai as genai

# --- 1. Keep-Alive Server (Render Free Tier ke liye) ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Live and Running!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheck)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# --- 2. API Keys Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8733316052:AAHcFiXmu3clwfjTMRx1P6_vN2T_FNblGjA")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6KJrHr8BMcULLiX3YV7u73UQmZkQuixHwJCpK4ozxD7CQ")

genai.configure(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

def get_swing_analysis(symbol: str) -> str:
    clean_sym = symbol.strip().upper()
    
    # NSE stock ke liye .NS lagana
    if not clean_sym.endswith(".NS") and not clean_sym.endswith(".BO") and not ("=" in clean_sym):
        search_sym = f"{clean_sym}.NS"
    else:
        search_sym = clean_sym

    # Reliable data fetch using Ticker history
    stock_ticker = yf.Ticker(search_sym)
    df = stock_ticker.history(period="6mo", interval="1d")

    # Agar .NS par na mile toh direct symbol check karein
    if df.empty:
        stock_ticker = yf.Ticker(clean_sym)
        df = stock_ticker.history(period="6mo", interval="1d")

    if df.empty or len(df) < 30:
        return f"❌ Stock data nahi mila for `{search_sym}`.\nKripya NSE symbol verify karein (jaise: TATAMOTORS, RELIANCE, INFY)."

    # MultiIndex column flatten agar ho
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Technical Indicators (Pure Pandas)
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()

    # RSI (14)
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # ATR (14)
    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift()).abs()
    lc = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['ATR'] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

    # 20-Day Average Volume
    df['Vol_SMA20'] = df['Volume'].rolling(window=20).mean()

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    prompt = f"""
    Act as a professional swing trader for Indian stock markets.
    Analyze this technical setup for {search_sym} on Daily candles:
    - Current Market Price: ₹{latest['Close']:.2f} (Previous Close: ₹{prev['Close']:.2f})
    - 20 EMA: ₹{latest['EMA_20']:.2f}
    - 50 EMA: ₹{latest['EMA_50']:.2f}
    - RSI (14): {latest['RSI']:.2f}
    - ATR (14): ₹{latest['ATR']:.2f}
    - Volume: {latest['Volume']:,} vs 20-Day Avg Volume: {latest['Vol_SMA20']:,}

    Output strictly in this format:
    🎯 Bias: [Bullish / Bearish / Neutral]
    📍 Entry Range: [Price bracket]
    🛑 Stop Loss: [Exact price level based on ATR / Swing support]
    🏁 Target 1: [Price]
    🏁 Target 2: [Price for 1:2 Risk-to-Reward]
    ⚡ Technical Logic: [2-3 sentences explaining setup]
    ⚠️ Invalidation: [Condition under which trade is cancelled]
    """

    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)

    header = (
        f"📊 Analysis: {search_sym}\n"
        f"• CMP: ₹{latest['Close']:.2f}\n"
        f"• RSI: {latest['RSI']:.1f} | 20 EMA: ₹{latest['EMA_20']:.1f}\n"
        f"-----------------------------------\n\n"
    )
    return header + response.text

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "👋 AI Swing Trading Bot active hai!\n\n"
        "Stock scan karne ke liye command bhejein:\n"
        "/swing TATAMOTORS\n"
        "/swing RELIANCE\n"
        "/swing INFY"
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['swing'])
def handle_swing(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Stock ka naam saath me likhein.\nExample: /swing TATAMOTORS")
        return

    stock = parts[1]
    wait_msg = bot.reply_to(message, f"⏳ {stock} ka setup calculate ho raha hai...")
    try:
        report = get_swing_analysis(stock)
        bot.edit_message_text(report, chat_id=wait_msg.chat.id, message_id=wait_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"⚠️ Error: {str(e)}", chat_id=wait_msg.chat.id, message_id=wait_msg.message_id)

print("Bot live chal raha hai...")
bot.infinity_polling()
