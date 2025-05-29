import pandas as pd
import numpy as np
import ta
import requests
import json
from datetime import datetime, timedelta
import time
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import asyncio
import logging
import nest_asyncio
import re
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
import shutil

nest_asyncio.apply()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === Bot Configuration ===
bot_token = '7663540460:AAFAfqA3Ur7zNUiRJ5qDWXmjIuTtcE491Gc'
chat_id = ['6151799236','1974773719']
bot = Bot(token=bot_token)

# List of authorized user IDs
AUTHORIZED_USERS = [6151799236, 1974773719]  # Add more user IDs as needed

# === NSE Website Scraper ===
class NSEScraper:
    def __init__(self):
        self.base_url = "https://www.nseindia.com"
        self.session = requests.Session()
        
        # Headers to mimic a real browser
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        self.session.headers.update(self.headers)
        
        # Initialize session with NSE
        self._init_session()
    
    def _init_session(self):
        """Initialize session by visiting NSE homepage using Selenium"""
        try:
            logger.info("Attempting Selenium-based session init to bypass CDN block")

            # Setup headless Chrome
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--window-size=1920,1080")

            # Check chromedriver availability
            chromedriver_path = shutil.which("chromedriver")
            if not chromedriver_path:
                raise FileNotFoundError("chromedriver not found in PATH")

            driver = webdriver.Chrome(service=Service(chromedriver_path), options=chrome_options)

            # Open NSE homepage
            driver.get("https://www.nseindia.com")
            time.sleep(5)  # Wait for cookies and JS to load

            selenium_cookies = driver.get_cookies()
            logger.info(f"Selenium got {len(selenium_cookies)} cookies")

            # Transfer cookies to requests session
            for cookie in selenium_cookies:
                self.session.cookies.set(cookie['name'], cookie['value'])

            driver.quit()

            # Verify cookies
            if self.session.cookies:
                logger.info("Successfully initialized session with Selenium cookies")
            else:
                logger.warning("Selenium ran, but no cookies set in session")

        except Exception as e:
            logger.error(f"Selenium session init failed: {str(e)}")

    
    def get_nifty_data(self, index_type="50"):
        """Fetch NIFTY data using Selenium"""
        try:
            logger.info(f"Selenium fetching NIFTY {index_type} data")
    
            # Setup headless Chrome
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--window-size=1920,1080")
    
            driver = webdriver.Chrome(service=Service(shutil.which("chromedriver")), options=chrome_options)
    
            # Open API endpoint directly in browser (may return raw JSON or get blocked)
            api_url = f"https://www.nseindia.com/api/allIndices"
            driver.get(api_url)
    
            time.sleep(5)
    
            # Try to parse JSON from page content
            page_source = driver.find_element(By.TAG_NAME, "pre").text  # JSON response shown in <pre>
            data = json.loads(page_source)
            driver.quit()
    
            # Parse the JSON data
            target_name = "NIFTY 50" if index_type == "50" else "NIFTY 100"
            for item in data.get("data", []):
                if item.get("index", "").upper() == target_name:
                    return self._parse_nifty_data(item, index_type)
    
            logger.warning(f"{target_name} data not found")
            return None
    
        except Exception as e:
            logger.error(f"Selenium API fetch failed: {str(e)}")
            return None

    
    def _parse_nifty_data(self, data, index_type):
        """Parse NIFTY data from NSE API response"""
        try:
            parsed_data = {
                'index_name': data.get('index', f'NIFTY {index_type}'),
                'last_price': float(data.get('last', 0)),
                'change': float(data.get('variation', 0)),
                'percent_change': float(data.get('percentChange', 0)),
                'open': float(data.get('open', 0)),
                'high': float(data.get('high', 0)),
                'low': float(data.get('low', 0)),
                'previous_close': float(data.get('previousClose', 0)),
                'timestamp': data.get('timeVal', ''),
                'market_status': 'Open' if data.get('last', 0) > 0 else 'Closed'
            }
            
            logger.info(f"Successfully parsed NIFTY {index_type} data: ₹{parsed_data['last_price']}")
            return parsed_data
            
        except Exception as e:
            logger.error(f"Error parsing NIFTY data: {str(e)}")
            return None
    
    def _scrape_nifty_alternative(self, index_type):
        """Alternative scraping method using NSE webpage"""
        try:
            logger.info(f"Trying alternative scraping for NIFTY {index_type}")
            
            # Direct URL for NIFTY page
            if index_type == "50":
                url = f"{self.base_url}/market-data/live-equity-market?symbol=NIFTY%2050"
            else:
                url = f"{self.base_url}/market-data/live-equity-market?symbol=NIFTY%20100"
            
            response = self.session.get(url, timeout=15)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Try to extract data from the webpage
                price_data = self._extract_price_from_html(soup, index_type)
                if price_data:
                    return price_data
            
            # Last resort - try to get data from market summary
            return self._get_market_summary_data(index_type)
            
        except Exception as e:
            logger.error(f"Alternative scraping failed: {str(e)}")
            return None
    
    def _extract_price_from_html(self, soup, index_type):
        """Extract price data from HTML content"""
        try:
            # Look for common patterns in NSE website
            price_elements = soup.find_all(['span', 'div'], class_=re.compile(r'price|value|last', re.I))
            
            # This is a simplified extraction - NSE website structure changes frequently
            # You might need to update these selectors based on current website structure
            
            extracted_data = {
                'index_name': f'NIFTY {index_type}',
                'last_price': 0.0,
                'change': 0.0,
                'percent_change': 0.0,
                'open': 0.0,
                'high': 0.0,
                'low': 0.0,
                'previous_close': 0.0,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'market_status': 'Unknown'
            }
            
            # Try to find numerical values that look like stock prices
            numbers = re.findall(r'\d{4,5}\.\d{2}', soup.get_text())
            if numbers:
                # Assume first large number is the current price
                extracted_data['last_price'] = float(numbers[0])
                logger.info(f"Extracted price from HTML: ₹{extracted_data['last_price']}")
                return extracted_data
            
            return None
            
        except Exception as e:
            logger.error(f"HTML extraction failed: {str(e)}")
            return None
    
    def _get_market_summary_data(self, index_type):
        """Get basic market data as last resort"""
        try:
            logger.info("Attempting to get basic market summary")
            
            # Try market data API endpoint
            url = f"{self.base_url}/api/market-data-pre-open?key=ALL"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # Process market summary data here
                # This would need to be customized based on actual API response structure
                pass
            
            # Return basic placeholder data if nothing else works
            return {
                'index_name': f'NIFTY {index_type}',
                'last_price': 0.0,
                'change': 0.0,
                'percent_change': 0.0,
                'open': 0.0,
                'high': 0.0,
                'low': 0.0,
                'previous_close': 0.0,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'market_status': 'Data Unavailable',
                'error': True
            }
            
        except Exception as e:
            logger.error(f"Market summary fallback failed: {str(e)}")
            return None
    
    def get_historical_data(self, index_type="50", days=7):
        """Attempt to get historical data for technical analysis"""
        try:
            logger.info(f"Fetching historical data for NIFTY {index_type}")
            
            # NSE historical data is typically not easily accessible via scraping
            # This is a simplified approach - you might need NSE historical data APIs
            
            # For now, return None to indicate historical data is not available
            # You could implement this by scraping historical charts or using other methods
            logger.warning("Historical data scraping not implemented - technical analysis will be limited")
            return None
            
        except Exception as e:
            logger.error(f"Historical data fetch failed: {str(e)}")
            return None

# Initialize NSE scraper
nse_scraper = NSEScraper()

# === Technical Analysis (Simplified without historical data) ===
def analyze_current_data(price_data):
    """Analyze current price data without historical indicators"""
    try:
        if not price_data or price_data.get('error'):
            return None
        
        analysis = {
            'current_price': price_data['last_price'],
            'change': price_data['change'],
            'percent_change': price_data['percent_change'],
            'day_range': f"₹{price_data['low']} - ₹{price_data['high']}",
            'opening_gap': price_data['last_price'] - price_data['open'] if price_data['open'] > 0 else 0,
            'market_sentiment': 'Bullish' if price_data['change'] > 0 else 'Bearish' if price_data['change'] < 0 else 'Neutral'
        }
        
        # Simple momentum analysis
        if abs(price_data['percent_change']) > 1.0:
            analysis['momentum'] = 'Strong'
        elif abs(price_data['percent_change']) > 0.5:
            analysis['momentum'] = 'Moderate'
        else:
            analysis['momentum'] = 'Weak'
        
        # Price position analysis
        if price_data['high'] > 0 and price_data['low'] > 0:
            price_position = (price_data['last_price'] - price_data['low']) / (price_data['high'] - price_data['low'])
            if price_position > 0.7:
                analysis['position'] = 'Near Day High'
            elif price_position < 0.3:
                analysis['position'] = 'Near Day Low'
            else:
                analysis['position'] = 'Mid Range'
        else:
            analysis['position'] = 'Unknown'
        
        return analysis
        
    except Exception as e:
        logger.error(f"Error in current data analysis: {str(e)}")
        return None

# === Market Prediction (Simplified) ===
def generate_simple_prediction(price_data, analysis):
    """Generate prediction based on available data"""
    try:
        if not price_data or not analysis:
            return "Insufficient data for prediction", "Neutral"
        
        prediction_score = 0
        signals = []
        
        # Price change analysis
        if price_data['percent_change'] > 1.0:
            prediction_score += 2
            signals.append("Strong upward momentum")
        elif price_data['percent_change'] > 0.5:
            prediction_score += 1
            signals.append("Positive momentum")
        elif price_data['percent_change'] < -1.0:
            prediction_score -= 2
            signals.append("Strong downward pressure")
        elif price_data['percent_change'] < -0.5:
            prediction_score -= 1
            signals.append("Negative momentum")
        
        # Opening gap analysis
        opening_gap = analysis.get('opening_gap', 0)
        if opening_gap > 50:
            prediction_score += 1
            signals.append("Positive opening gap")
        elif opening_gap < -50:
            prediction_score -= 1
            signals.append("Negative opening gap")
        
        # Position in day's range
        if analysis.get('position') == 'Near Day High':
            prediction_score += 1
            signals.append("Trading near day high")
        elif analysis.get('position') == 'Near Day Low':
            prediction_score -= 1
            signals.append("Trading near day low")
        
        # Generate final prediction
        if prediction_score >= 2:
            prediction = "Bullish (70% confidence)"
        elif prediction_score >= 1:
            prediction = "Mildly Bullish (60% confidence)"
        elif prediction_score <= -2:
            prediction = "Bearish (70% confidence)"
        elif prediction_score <= -1:
            prediction = "Mildly Bearish (60% confidence)"
        else:
            prediction = "Neutral (50% confidence)"
        
        detailed_analysis = "Signals: " + " | ".join(signals[:3]) if signals else "Limited signals available"
        
        return detailed_analysis, prediction
        
    except Exception as e:
        logger.error(f"Error generating prediction: {str(e)}")
        return "Prediction analysis failed", "Neutral"

# === Authorization Check ===
def is_authorized(user_id):
    """Check if the user is authorized to use this bot"""
    return int(user_id) in AUTHORIZED_USERS

# === Command Handlers ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        logger.warning(f"Unauthorized access attempt from user {user_id} ({username})")
        return
    
    welcome_text = f"""
🚀 *Welcome {username}!*

*NIFTY Trading Analysis Bot*
📊 *Direct NSE Data Scraping*

📈 Available Commands:
• `/nifty50` - Get NIFTY 50 analysis
• `/nifty100` - Get NIFTY 100 analysis  
• `/quick50` - Quick NIFTY 50 quote
• `/quick100` - Quick NIFTY 100 quote
• `/predict50` - NIFTY 50 prediction
• `/predict100` - NIFTY 100 prediction
• `/status` - Check scraper status
• `/help` - Show help menu

💡 *Data Source:* NSE India Website
⚡ *Real-time scraping* from official NSE
    """
    await update.message.reply_text(welcome_text, parse_mode='markdown')
    logger.info(f"User {user_id} ({username}) started the bot")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /help command"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    help_text = """
📚 *NIFTY Trading Bot - Command Guide*

*Main Analysis Commands:*
• `/nifty50` - Complete NIFTY 50 analysis
• `/nifty100` - Complete NIFTY 100 analysis

*Quick Commands:*
• `/quick50` - Fast NIFTY 50 price update
• `/quick100` - Fast NIFTY 100 price update

*Prediction Commands:*
• `/predict50` - Market prediction for NIFTY 50
• `/predict100` - Market prediction for NIFTY 100

*Utility Commands:*
• `/status` - Check NSE scraper status
• `/help` - Show this help menu
• `/start` - Restart the bot

📊 *Features:*
• Direct NSE website scraping
• Real-time price data
• Market sentiment analysis
• Intraday predictions
• Price position analysis

🌐 *Data Source:* NSE India Official Website
⚠️ *Note:* Historical technical indicators require NSE historical data access
    """
    await update.message.reply_text(help_text, parse_mode='markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check NSE scraper status"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    await update.message.reply_text("🔍 Checking NSE scraper status...")
    
    status_msg = "📊 *NSE Scraper Status Report*\n\n"
    
    # Test NSE connection
    try:
        test_data = nse_scraper.get_nifty_data("50")
        if test_data and not test_data.get('error'):
            status_msg += "✅ NSE Website: *Accessible*\n"
            status_msg += f"✅ NIFTY 50 Data: *Available* (₹{test_data['last_price']:.2f})\n"
        else:
            status_msg += "⚠️ NSE Website: *Limited Access*\n"
    except Exception as e:
        status_msg += "❌ NSE Website: *Connection Issues*\n"
        status_msg += f"Error: {str(e)[:50]}...\n"
    
    status_msg += f"\n🤖 Bot Status: *Active*\n"
    status_msg += f"👤 Authorized Users: *{len(AUTHORIZED_USERS)}*\n"
    status_msg += f"🕐 Last Check: *{datetime.now().strftime('%H:%M:%S')}*\n"
    status_msg += f"📡 Data Source: *NSE India Website*"
    
    await update.message.reply_text(status_msg, parse_mode='markdown')

async def quick_nifty_command(update: Update, context: ContextTypes.DEFAULT_TYPE, index_type="50"):
    """Quick NIFTY price update"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    await update.message.reply_text(f"⚡ Scraping NIFTY {index_type} from NSE...")
    
    try:
        price_data = nse_scraper.get_nifty_data(index_type)
        
        if price_data and not price_data.get('error'):
            change_emoji = "📈" if price_data['change'] > 0 else "📉" if price_data['change'] < 0 else "➖"
            
            msg = f"""
{change_emoji} *NIFTY {index_type} - Live from NSE*

💰 *Current Price:* ₹{price_data['last_price']:.2f}
📊 *Change:* {price_data['change']:+.2f} ({price_data['percent_change']:+.2f}%)
📈 *High:* ₹{price_data['high']:.2f}
📉 *Low:* ₹{price_data['low']:.2f}
🔓 *Open:* ₹{price_data['open']:.2f}
🔒 *Previous Close:* ₹{price_data['previous_close']:.2f}

📊 *Market Status:* {price_data['market_status']}
🕐 *Updated:* {price_data['timestamp']}
📡 *Source:* NSE India Website
            """
        else:
            msg = f"❌ Unable to fetch NIFTY {index_type} data from NSE website. The website may be temporarily inaccessible or the structure may have changed."
        
        await update.message.reply_text(msg, parse_mode='markdown')
        
    except Exception as e:
        logger.error(f"Error in quick NIFTY {index_type} command: {str(e)}")
        await update.message.reply_text(f"❌ Error scraping NIFTY {index_type} data: NSE website may be down or blocking requests.")

async def nifty_analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE, index_type="50"):
    """Complete NIFTY analysis"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    await update.message.reply_text(f"📊 Analyzing NIFTY {index_type} from NSE website...")
    
    try:
        price_data = nse_scraper.get_nifty_data(index_type)
        
        if not price_data or price_data.get('error'):
            await update.message.reply_text(f"❌ Unable to fetch NIFTY {index_type} data from NSE website. Please try again later.")
            return
        
        # Analyze current data
        analysis = analyze_current_data(price_data)
        
        if not analysis:
            await update.message.reply_text(f"❌ Analysis failed for NIFTY {index_type}.")
            return
        
        change_emoji = "📈" if price_data['change'] > 0 else "📉" if price_data['change'] < 0 else "➖"
        
        # Format message
        msg = f"""
{change_emoji} *NIFTY {index_type} - Complete Analysis*

💰 *Price:* ₹{analysis['current_price']:.2f}
📊 *Change:* {analysis['change']:+.2f} ({analysis['percent_change']:+.2f}%)

📊 *Market Analysis:*
• Sentiment: {analysis['market_sentiment']}
• Momentum: {analysis['momentum']}
• Position: {analysis['position']}
• Day Range: {analysis['day_range']}
• Opening Gap: ₹{analysis['opening_gap']:+.2f}

📊 *Market Status:* {price_data['market_status']}

⚠️ *Note:* Analysis based on current session data
Historical indicators require NSE historical data access

📡 *Data Source:* NSE India Website
🕐 *Time:* {datetime.now().strftime('%H:%M:%S')}
        """
        
        await update.message.reply_text(msg, parse_mode='markdown')
        
    except Exception as e:
        logger.error(f"Error in NIFTY {index_type} analysis: {str(e)}")
        await update.message.reply_text(f"❌ Analysis failed for NIFTY {index_type}: NSE website may be inaccessible.")

async def prediction_command(update: Update, context: ContextTypes.DEFAULT_TYPE, index_type="50"):
    """Generate prediction for NIFTY"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    await update.message.reply_text(f"🔮 Generating NIFTY {index_type} prediction from NSE data...")
    
    try:
        price_data = nse_scraper.get_nifty_data(index_type)
        
        if not price_data or price_data.get('error'):
            await update.message.reply_text(f"❌ Cannot generate prediction - no data available for NIFTY {index_type}.")
            return
        
        analysis = analyze_current_data(price_data)
        if not analysis:
            await update.message.reply_text(f"❌ Prediction analysis failed for NIFTY {index_type}.")
            return
        
        detailed_analysis, prediction = generate_simple_prediction(price_data, analysis)
        
        msg = f"""
🔮 *NIFTY {index_type} - Market Prediction*

🎯 *Outlook:* {prediction}

📊 *Analysis:*
{detailed_analysis}

📈 *Current Factors:*
• Price Momentum: {analysis['momentum']}
• Market Sentiment: {analysis['market_sentiment']}
• Intraday Position: {analysis['position']}

⚠️ *Disclaimer:* Prediction based on current session data only. 
Not financial advice. Always do your own research.

📡 *Data Source:* NSE India Website
🕐 *Generated:* {datetime.now().strftime('%H:%M:%S')}
        """
        
        await update.message.reply_text(msg, parse_mode='markdown')
        
    except Exception as e:
        logger.error(f"Error in NIFTY {index_type} prediction: {str(e)}")
        await update.message.reply_text(f"❌ Prediction failed for NIFTY {index_type}: NSE data unavailable.")

# === Command wrapper functions ===
async def nifty50_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await nifty_analysis_command(update, context, "50")

async def nifty100_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await nifty_analysis_command(update, context, "100")

async def quick50_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await quick_nifty_command(update, context, "50")

async def quick100_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await quick_nifty_command(update, context, "100")

async def predict50_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await prediction_command(update, context, "50")

async def predict100_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await prediction_command(update, context, "100")

# === Error Handler ===
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and notify user"""
    logger.error(f"Update {update} caused error: {context.error}")
    
    if update and hasattr(update, 'effective_user'):
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="❌ An unexpected error occurred. NSE website may be temporarily inaccessible."
            )
        except:
            pass

# === Unauthorized Handler ===
async def unauthorized_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from unauthorized users"""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        logger.warning(f"Unauthorized access attempt from user {user_id}")

# === Main Bot Setup ===
async def main():
    """Set up the Telegram bot with NSE scraping"""
    # Create the Application
    application = Application.builder().token(bot_token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    
    # NIFTY analysis commands
    application.add_handler(CommandHandler("nifty50", nifty50_command))
    application.add_handler(CommandHandler("nifty100", nifty100_command))
    
    # Quick update commands  
    application.add_handler(CommandHandler("quick50", quick50_command))
    application.add_handler(CommandHandler("quick100", quick100_command))
    
    # Prediction commands
    application.add_handler(CommandHandler("predict50", predict50_command))
    application.add_handler(CommandHandler("predict100", predict100_command))
    
    # Backward compatibility
    application.add_handler(CommandHandler("nifty", nifty50_command))
    
    # Unauthorized access handler
    application.add_handler(MessageHandler(filters.ALL, unauthorized_handler))
    
    # Error handler
    application.add_error_handler(error_handler)

    # Start polling
    logger.info("🚀 NSE Scraping Bot started and polling for messages")
    print("NSE Scraping Bot is running... Press Ctrl+C to stop")
    await application.run_polling()

# === Run the Bot ===
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("\n🛑 Bot stopped gracefully")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        print(f"❌ Bot crashed: {str(e)}")
