import yfinance as yf
import pandas as pd
import numpy as np
import ta
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import asyncio
import time
import logging
import nest_asyncio
import pandas as pd


nest_asyncio.apply()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === Telegram Setup ===
bot_token = '8089007262:AAFgApsN7gHtzmLmfz8BAsjIUrgAbTAobKg'
chat_id = '1974773719'
bot = Bot(token=bot_token)
alpha_api_key = 'S4WZ2N6CVAS82RJG'


# List of authorized user IDs (add your Telegram user ID here)
AUTHORIZED_USERS = [1974773719]  # Replace with your actual Telegram user ID

# === Manual RSI Calculation ===
def calculate_rsi_manually(prices, window=14):
    """Calculate RSI manually as fallback if ta library fails"""
    try:
        # Convert to numpy array for calculations
        prices_array = np.array(prices)
        
        # Calculate price changes
        deltas = np.diff(prices_array)
        
        # Create seed values
        seed = deltas[:window+1]
        up = seed[seed >= 0].sum()/window
        down = -seed[seed < 0].sum()/window
        
        # Calculate RS values
        rs = up/down
        
        # Calculate RSI
        rsi = np.zeros_like(prices_array)
        rsi[:window] = 100. - 100./(1. + rs)
        
        # Calculate RSI for remaining prices
        for i in range(window, len(prices_array)):
            delta = deltas[i-1]
            
            if delta > 0:
                upval = delta
                downval = 0
            else:
                upval = 0
                downval = -delta
                
            up = (up * (window-1) + upval) / window
            down = (down * (window-1) + downval) / window
            
            rs = up/down if down != 0 else 100  # Avoid division by zero
            rsi[i] = 100. - 100./(1. + rs)
            
        return rsi
    except Exception as e:
        logger.error(f"Error in manual RSI calculation: {str(e)}")
        return np.ones(len(prices)) * 50  # Return neutral values on error

# === Manual MACD Calculation ===
def calculate_macd_manually(prices, fast=12, slow=26, signal=9):
    """Calculate MACD manually as fallback if ta library fails"""
    try:
        # Convert to numpy array
        prices_array = np.array(prices)
        
        # Calculate EMAs
        ema_fast = np.zeros_like(prices_array)
        ema_slow = np.zeros_like(prices_array)
        macd_line = np.zeros_like(prices_array)
        signal_line = np.zeros_like(prices_array)
        
        # Initialize with simple moving average
        ema_fast[:fast] = np.mean(prices_array[:fast])
        ema_slow[:slow] = np.mean(prices_array[:slow])
        
        # EMA factors
        k_fast = 2.0 / (fast + 1)
        k_slow = 2.0 / (slow + 1)
        k_signal = 2.0 / (signal + 1)
        
        # Calculate EMAs
        for i in range(fast, len(prices_array)):
            ema_fast[i] = (prices_array[i] - ema_fast[i-1]) * k_fast + ema_fast[i-1]
        
        for i in range(slow, len(prices_array)):
            ema_slow[i] = (prices_array[i] - ema_slow[i-1]) * k_slow + ema_slow[i-1]
            macd_line[i] = ema_fast[i] - ema_slow[i]
        
        # Calculate signal line
        signal_line[slow:slow+signal] = np.mean(macd_line[slow:slow+signal])
        for i in range(slow+signal, len(prices_array)):
            signal_line[i] = (macd_line[i] - signal_line[i-1]) * k_signal + signal_line[i-1]
        
        return macd_line, signal_line
    except Exception as e:
        logger.error(f"Error in manual MACD calculation: {str(e)}")
        # Return neutral values on error
        return np.zeros(len(prices)), np.zeros(len(prices))
    
# === NIFTY50 Data Fetch with retry ===
def fetch_nifty50_data(max_retries=3, ticker="^NSEI"):
    """Fetch NIFTY50 data with retry mechanism"""
    for attempt in range(max_retries):
        try:
            logger.info(f"Fetching data for {ticker}, attempt {attempt+1}/{max_retries}")
            # Explicitly set auto_adjust to handle the warning
            data = yf.download(tickers=ticker, period="1d", interval="15m", auto_adjust=True)
            
            # Check if data is empty
            if data.empty:
                logger.warning(f"Attempt {attempt+1}: Empty data returned for {ticker}")
                if attempt < max_retries - 1:
                    time.sleep(5)  # Wait before retrying
                    continue
                # Try alternative ticker as fallback
                logger.info("Trying alternative ticker 'NSEI.NS'")
                data = yf.download(tickers="NSEI.NS", period="1d", interval="15m", auto_adjust=True)
                if not data.empty:
                    return data
                
                # If still empty, try another alternative
                logger.info("Trying alternative ticker 'NIFTY_50.NS'")
                data = yf.download(tickers="NIFTY_50.NS", period="1d", interval="15m", auto_adjust=True)
                if not data.empty:
                    return data
                
                # Create a minimal dummy dataframe as last resort
                logger.warning("No data fetched, using dummy data")
                return create_dummy_data()
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching data, attempt {attempt+1}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(5)  # Wait before retrying
            else:
                logger.error("Max retries exceeded, using dummy data")
                return create_dummy_data()

def create_dummy_data():
    """Create dummy data as fallback to prevent calculation errors"""
    logger.warning("Creating dummy data for fallback")
    index = pd.date_range(start=pd.Timestamp.now().floor('D'), periods=10, freq='15min')
    data = {
        'Open': [17000 + i for i in range(10)],
        'High': [17010 + i for i in range(10)],
        'Low': [16990 + i for i in range(10)],
        'Close': [17005 + i for i in range(10)],
        'Volume': [1000000 for _ in range(10)]
    }
    return pd.DataFrame(data, index=index)

# === Indicator Calculation ===
def analyze_indicators(df):
    """Calculate technical indicators on the dataframe"""
    try:
        # Check if dataframe is not empty before calculating indicators
        if not df.empty and len(df) > 14:  # Need at least 14 periods for RSI
            # Convert the Close column to a simple 1D series
            # The .squeeze() method will convert (25,1) shape to (25,) shape
            close_series = df['Close'].squeeze()
            
            # Make sure it's a Series, not a DataFrame
            if isinstance(close_series, pd.DataFrame):
                close_series = close_series.iloc[:, 0]
            
            # Ensure it's a flat Series with no multi-dimensional structure
            logger.info(f"Close series shape after squeeze: {close_series.shape if hasattr(close_series, 'shape') else 'scalar'}")
            
            # Calculate RSI with the simple 1D series
            rsi_indicator = ta.momentum.RSIIndicator(close_series, window=14)
            df['RSI'] = rsi_indicator.rsi()
            
            # Calculate MACD with the simple 1D series
            macd = ta.trend.MACD(close_series)
            df['MACD'] = macd.macd()
            df['Signal'] = macd.macd_signal()
        else:
            logger.warning("Not enough data for indicators, using placeholder values")
            df['RSI'] = 50.0  # Neutral RSI value
            df['MACD'] = 0.0
            df['Signal'] = 0.0
        return df
    except Exception as e:
        logger.error(f"Error calculating indicators: {str(e)}")
        # Add placeholder columns to avoid downstream errors
        df['RSI'] = 50.0
        df['MACD'] = 0.0
        df['Signal'] = 0.0
        return df

# === Candlestick Pattern Detection ===
def detect_candlestick(df):
    """Detect candlestick pattern from the latest candle"""
    try:
        latest = df.iloc[-1].copy()  # Get a copy of the latest row
        
        # Extract scalar values from Series using iloc[0] to avoid FutureWarning
        open_price = float(latest['Open'].iloc[0]) if isinstance(latest['Open'], pd.Series) else float(latest['Open'])
        close_price = float(latest['Close'].iloc[0]) if isinstance(latest['Close'], pd.Series) else float(latest['Close'])
        high = float(latest['High'].iloc[0]) if isinstance(latest['High'], pd.Series) else float(latest['High'])
        low = float(latest['Low'].iloc[0]) if isinstance(latest['Low'], pd.Series) else float(latest['Low'])

        body = abs(close_price - open_price)
        candle_range = high - low
        upper_shadow = high - max(open_price, close_price)
        lower_shadow = min(open_price, close_price) - low

        pattern = "No clear pattern"
        if close_price > open_price and body > upper_shadow and body > lower_shadow:
            pattern = "Bullish Engulfing"
        elif open_price > close_price and body > upper_shadow and body > lower_shadow:
            pattern = "Bearish Engulfing"
        elif body < candle_range * 0.1:
            pattern = "Doji"
        elif lower_shadow > 2 * body:
            pattern = "Hammer"
        elif upper_shadow > 2 * body:
            pattern = "Shooting Star"

        return pattern
    except Exception as e:
        logger.error(f"Error detecting candlestick pattern: {str(e)}")
        return "Unable to determine pattern"

# === Suggestion Generator ===
def get_suggestion(rsi_value, macd, signal):
    """Generate trading suggestions based on technical indicators"""
    try:
        # Convert Series to float if needed using iloc[0] to avoid FutureWarning
        if isinstance(rsi_value, pd.Series):
            rsi_value = float(rsi_value.iloc[0])
        if isinstance(macd, pd.Series):
            macd = float(macd.iloc[0])
        if isinstance(signal, pd.Series):
            signal = float(signal.iloc[0])
            
        # Ensure we're working with scalar values
        rsi_value = float(rsi_value)
        macd = float(macd)
        signal = float(signal)

        if rsi_value > 70:
            rsi_trend = "Overbought, possible reversal soon"
        elif rsi_value < 30:
            rsi_trend = "Oversold, possible bounce"
        else:
            rsi_trend = "Normal range"

        macd_signal = "Bullish" if macd > signal else "Bearish"

        if macd_signal == "Bullish" and rsi_value < 70:
            suggestion = "Possible Uptrend"
        elif macd_signal == "Bearish" and rsi_value > 30:
            suggestion = "Possible Downtrend"
        else:
            suggestion = "Neutral / Wait and watch"

        return rsi_trend, macd_signal, suggestion
    except Exception as e:
        logger.error(f"Error generating suggestion: {str(e)}")
        return "Normal range", "Neutral", "Wait and watch"

# === Send Telegram Message (Async) ===
async def send_telegram_message(text, user_id=None):
    """Send message to Telegram asynchronously"""
    try:
        # If user_id is provided, send to that user, otherwise use default chat_id
        recipient = user_id if user_id else chat_id
        await bot.send_message(chat_id=recipient, text=text, parse_mode='markdown')
        logger.info(f"Message sent successfully to {recipient}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {str(e)}")

# === Authorization Check ===
def is_authorized(user_id):
    """Check if the user is authorized to use this bot"""
    return int(user_id) in AUTHORIZED_USERS

# === Command Handler for the /nifty command ===
async def nifty_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /nifty command for authenticated users"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("You are not authorized to use this bot.")
        logger.warning(f"Unauthorized access attempt from user {user_id}")
        return
    
    await update.message.reply_text("Fetching NIFTY50 data, please wait...")
    await run_bot_for_user(user_id)

# === Help command handler ===
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /help command"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("You are not authorized to use this bot.")
        logger.warning(f"Unauthorized access attempt from user {user_id}")
        return
    
    help_text = """
*NIFTY50 Trading Bot Commands:*

/nifty - Get the latest NIFTY50 analysis
/help - Show this help message
    """
    await update.message.reply_text(help_text, parse_mode='markdown')

# === Start command handler ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if not is_authorized(user_id):
        await update.message.reply_text("You are not authorized to use this bot.")
        logger.warning(f"Unauthorized access attempt from user {user_id} ({username})")
        return
    
    welcome_text = f"""
Hello {username}!

Welcome to the NIFTY50 Trading Bot. This bot provides technical analysis for NIFTY50.

Use /nifty to get the latest analysis.
Use /help to see all available commands.
    """
    await update.message.reply_text(welcome_text)
    logger.info(f"User {user_id} ({username}) started the bot")

# === Modified Bot Logic to respond to a specific user ===
async def run_bot_for_user(user_id=None):
    """Async version of the main bot function that can target a specific user"""
    try:
        logger.info(f"Starting NIFTY50 signal update for user {user_id if user_id else 'default'}")
        df = fetch_nifty50_data()
        
        # Log data shape to diagnose issues
        logger.info(f"Data fetched: {df.shape[0]} rows x {df.shape[1]} columns")
        
        # Early return if still no data
        if df.empty:
            error_msg = "Unable to retrieve market data. Service temporarily unavailable."
            logger.error(error_msg)
            await send_telegram_message(error_msg, user_id)
            return
            
        df = analyze_indicators(df)

        latest = df.iloc[-1]
        
        # Extract scalar values from Series using iloc[0] to avoid FutureWarning
        price = float(latest['Close'].iloc[0]) if isinstance(latest['Close'], pd.Series) else float(latest['Close'])
        rsi_val = float(latest['RSI'].iloc[0]) if isinstance(latest['RSI'], pd.Series) else float(latest['RSI'])
        macd_val = float(latest['MACD'].iloc[0]) if isinstance(latest['MACD'], pd.Series) else float(latest['MACD'])
        signal_val = float(latest['Signal'].iloc[0]) if isinstance(latest['Signal'], pd.Series) else float(latest['Signal'])
        
        candle = detect_candlestick(df)
        rsi_trend, macd_signal, suggestion = get_suggestion(rsi_val, macd_val, signal_val)

        msg = f"""*NIFTY50 Signal Update:*

Price: ₹{price:.2f}

RSI: {rsi_val:.2f} ({rsi_trend})

MACD: {macd_signal} crossover detected

Candlestick Pattern: {candle}

Market Behaviour: {suggestion}
"""
        logger.info("Sending message to Telegram")
        await send_telegram_message(msg, user_id)
        
    except Exception as e:
        error_msg = f"An error occurred: {str(e)}"
        logger.error(error_msg)
        try:
            await send_telegram_message(error_msg, user_id)
        except Exception as telegram_error:
            logger.error(f"Failed to send error message to Telegram: {str(telegram_error)}")

# === Schedule function ===
async def scheduled_update():
    """Send scheduled updates to all authorized users"""
    for user_id in AUTHORIZED_USERS:
        await run_bot_for_user(user_id)

# === Set up the interactive bot ===
async def main():
    """Set up the Telegram bot with command handlers using the newer API"""
    # Create the Application
    application = Application.builder().token(bot_token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("nifty", nifty_command))

    # Optional: Catch-all message handler for unauthorized users
    async def unauthorized_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_authorized(user_id):
            await update.message.reply_text("You are not authorized to use this bot.")
            logger.warning(f"Unauthorized access attempt from user {user_id}")

    application.add_handler(MessageHandler(filters.COMMAND, unauthorized_handler))

    # Error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}")
    application.add_error_handler(error_handler)

    # Start polling
    logger.info("Bot started and polling for messages")
    await application.run_polling()

# === Original method for backward compatibility ===
async def run_bot_async():
    """Async version of the main bot function (original method)"""
    await run_bot_for_user()

def run_bot():
    """Main function to run the trading bot"""
    asyncio.run(run_bot_async())

# === RUN THE BOT ===
if __name__ == "__main__":
    # Choose which method to use based on your needs
    # For scheduled updates, use run_bot()
    # For interactive command-based bot, use asyncio.run(main())
    asyncio.run(main())
  # Run the interactive bot
    # run_bot()  # Uncomment this and comment out main() if you want to run the original scheduled method instead
