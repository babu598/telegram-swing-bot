import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import google.generativeai as genai

# --- 1. Render Port Listener (Bot ko 24/7 zinda rakhne ke liye) ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running Live!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheck)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# --- 2. Environment Variables Se Keys Read Karein ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

def get_swing_analysis(symbol: str) -> str:
    clean_sym = symbol.strip().upper()
    if not clean_sym.endswith(".NS") and not clean_sym.endswith(".BO"):
        clean_sym += ".NS"

    df = yf.download(clean_sym, period="6mo", interval="1d", progress=False)
    if df.empty or len(df) < 50:
        return f"❌ Stock data nahi mila for {clean_sym}. Symbol verify karein."

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df['EMA_20'] = ta.ema(df['Close'], length=20)
    df['EMA_50'] = ta.ema(df['Close'], length=50)
    df['RSI'] = ta.rsi(df['Close'], length=14)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    df['Vol_SMA20'] = ta.sma(df['Volume'], length=20)

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    prompt = f"""
    Act as a professional swing trader for Indian stock markets.
    Analyze this technical setup for {clean_sym} on Daily candles:
    - Current Market Price: ₹{latest['Close']:.2f} (Prev Close: ₹{prev['Close']:.2f})
    - 20 EMA: ₹{latest['EMA_20']:.2f}
    - 50 EMA: ₹{latest['EMA_50']:.2f}
    - RSI (14): {latest['RSI']:.2f}
    - ATR (14): ₹{latest['ATR']:.2f}
    - Volume: {latest['Volume']:,} vs 20-Day Avg Volume: {latest['Vol_SMA20']:,}

    Output the plan strictly in this format:
    🎯 Bias: [Bullish / Bearish / Neutral]
    📍 Entry Range: [Price bracket]
    🛑 Stop Loss: [Exact price level based on ATR / Swing support]
    🏁 Target 1: [Price]
    🏁 Target 2: [Price for 1:2 Risk-to-Reward]
    ⚡ Technical Logic: [2-3 sentences]
    ⚠️ Invalidation: [Condition under which trade is cancelled]
    """

    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)

    header = (
        f"📊 Analysis: {clean_sym}\n"
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
    wait_msg = bot.reply_to(message, f"⏳ {stock} ka technical setup calculate ho raha hai...")
    try:
        report = get_swing_analysis(stock)
        bot.edit_message_text(report, chat_id=wait_msg.chat.id, message_id=wait_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"⚠️ Error: {str(e)}", chat_id=wait_msg.chat.id, message_id=wait_msg.message_id)

print("Bot live chal raha hai...")
bot.infinity_polling()
