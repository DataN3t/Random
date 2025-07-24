import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import time
import threading
import os
import logging
from datetime import datetime, timezone
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pytz
import csv

# Initialize logger
logging.basicConfig(filename='trading_bot.log', level=logging.INFO, format='%(asctime)s:%(levelname)s:%(message)s')
logger = logging.getLogger()

# Kraken API setup - Use environment variables for security
kraken_api_key = os.getenv('KRAKEN_API_KEY')
kraken_api_secret = os.getenv('KRAKEN_API_SECRET')
exchange = ccxt.kraken({
    'apiKey': kraken_api_key,
    'secret': kraken_api_secret,
})

# Email Keys - Use env vars
email_sender = os.getenv('EMAIL_SENDER', 'jacob.knol@data-net.io')
email_password = os.getenv('EMAIL_PASSWORD', 'D@ta-N3t')
email_receiver = os.getenv('EMAIL_RECEIVER', 'jacob.knol@data-net.io')
smtp_server = 'smtp-auth.mailprotect.be'
smtp_port = 587

# Bot parameters
pair = 'XRP/USDC'
timeframe = '5m'  # 5-minute chart
initial_capital = 200  # Initial capital in USDC
poll_interval = 30  # Seconds between checks (hybrid approach)
rsi_period = 14
stoch_fastk_period = 14
stoch_slowd_period = 3
ema_periods = [20, 50, 100, 200]  # For stacked trend filter
volume_window = 14  # For average volume
rsi_buy_threshold = 30  # Oversold for buy (tightened for more signals)
rsi_sell_threshold = 70  # Overbought for sell
stoch_buy_threshold = 20  # Oversold for %K
stoch_sell_threshold = 80  # Overbought for %K

# CSV file path - Use relative or cloud storage in production
csv_file_path = 'xrp_usdc_trading_bot_data.csv'

def initialize_csv(file_path):
    if not os.path.exists(file_path):
        with open(file_path, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Date & Time', 'Price in USDC', 'Signal', 'Initial Capital', 'Total Profit', 'Total Profit (%)', 'Profit From Last Trade', 'Profit From Last Trade (%)', 'Date & Time Trade', 'RSI', '%K', '%D', 'Volume', 'Average Volume', 'EMA20', 'EMA50', 'EMA100', 'EMA200'])

initialize_csv(csv_file_path)

def get_cet_time():
    cet = pytz.timezone('CET')
    return datetime.now(cet).strftime('%Y-%m-%d %H:%M:%S')

def fetch_ohlcv(limit=300):
    try:
        ohlcv = exchange.fetch_ohlcv(pair, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"Error fetching OHLCV: {e}")
        return None

def calculate_indicators(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Stochastic
    low_min = df['low'].rolling(window=stoch_fastk_period).min()
    high_max = df['high'].rolling(window=stoch_fastk_period).max()
    df['%K'] = 100 * (df['close'] - low_min) / (high_max - low_min)
    df['%D'] = df['%K'].rolling(window=stoch_slowd_period).mean()
    
    # EMAs
    for period in ema_periods:
        df[f'ema{period}'] = df['close'].ewm(span=period, adjust=False).mean()
    
    # Volume Avg
    df['volume_avg'] = df['volume'].rolling(window=volume_window).mean()
    
    return df

def is_ema_bullish(df):
    latest = df.iloc[-1]
    return (latest['ema20'] > latest['ema50'] > latest['ema100'] > latest['ema200'])

def is_ema_bearish(df):
    latest = df.iloc[-1]
    return (latest['ema20'] < latest['ema50'] < latest['ema100'] < latest['ema200'])

def determine_signal(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest  # For crossover check
    
    buy_condition = (
        latest['rsi'] < rsi_buy_threshold and
        latest['%K'] < stoch_buy_threshold and
        latest['%K'] > latest['%D'] and prev['%K'] <= prev['%D'] and  # Bullish crossover
        is_ema_bullish(df) and
        latest['volume'] > latest['volume_avg']
    )
    
    sell_condition = (
        latest['rsi'] > rsi_sell_threshold and
        latest['%K'] > stoch_sell_threshold and
        latest['%K'] < latest['%D'] and prev['%K'] >= prev['%D'] and  # Bearish crossover
        is_ema_bearish(df) and
        latest['volume'] > latest['volume_avg']
    )
    
    if buy_condition:
        return 'Buy'
    elif sell_condition:
        return 'Sell'
    return 'Hold'

def place_order(side, amount):
    try:
        if side == 'buy':
            order = exchange.create_market_buy_order(pair, amount)
        else:
            order = exchange.create_market_sell_order(pair, amount)
        logger.info(f"Order placed: {side} {amount} XRP/USDC. Result: {order}")
        return order
    except Exception as e:
        logger.error(f"Error placing {side} order: {e}")
        return None

def send_email(subject, message):
    try:
        msg = MIMEMultipart()
        msg['From'] = email_sender
        msg['To'] = email_receiver
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(email_sender, email_password)
        server.sendmail(email_sender, email_receiver, msg.as_string())
        server.quit()
        logger.info(f"Email sent: {subject} - {message}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

# Bot loop function
def trading_bot_loop(stop_event, status_placeholder):
    capital = initial_capital
    position = 0  # Holding XRP amount
    trade_log = []
    last_candle_time = None
    last_notification_hour = datetime.now(pytz.timezone('CET')).hour

    while not stop_event.is_set():
        try:
            # Fetch current price
            ticker = exchange.fetch_ticker(pair)
            current_price = ticker['last']
            current_time_cet = get_cet_time()

            # Hourly status email
            current_hour = datetime.now(pytz.timezone('CET')).hour
            if current_hour != last_notification_hour:
                last_notification_hour = current_hour
                send_email('Bot Status Notification', f'Trading bot is running smoothly as of {current_time_cet}.')

            # Fetch OHLCV and check for new candle
            df = fetch_ohlcv()
            if df is None:
                raise Exception("Failed to fetch OHLCV")

            latest_timestamp = df['timestamp'].iloc[-1]
            if last_candle_time is None or latest_timestamp > last_candle_time:
                last_candle_time = latest_timestamp
                df = calculate_indicators(df)
                latest = df.iloc[-1]

                signal = determine_signal(df)

                # Log and print info (adapt for Streamlit)
                total_profit = capital + (position * current_price) - initial_capital if position > 0 else capital - initial_capital
                total_profit_pct = (total_profit / initial_capital) * 100
                last_trade_profit = trade_log[-1][3] if trade_log else 0  # Simplified
                last_trade_profit_pct = (last_trade_profit / initial_capital) * 100

                log_message = f"Signal: {signal} | Price: {current_price:.4f} | RSI: {latest['rsi']:.2f} | %K: {latest['%K']:.2f} | %D: {latest['%D']:.2f} | Volume: {latest['volume']:.2f} | Avg Vol: {latest['volume_avg']:.2f} | EMA20: {latest['ema20']:.2f} | EMA50: {latest['ema50']:.2f} | EMA100: {latest['ema100']:.2f} | EMA200: {latest['ema200']:.2f}"
                logger.info(log_message)
                
                # Update CSV
                with open(csv_file_path, mode='a', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow([current_time_cet, current_price, signal, initial_capital, total_profit, total_profit_pct, last_trade_profit, last_trade_profit_pct, current_time_cet, latest['rsi'], latest['%K'], latest['%D'], latest['volume'], latest['volume_avg'], latest['ema20'], latest['ema50'], latest['ema100'], latest['ema200']])

                # Update Streamlit status
                status_placeholder.text(f"Last Check: {current_time_cet}\n{log_message}")

                # Execute trade
                if signal == 'Buy' and position == 0 and capital > 0:
                    amount_to_buy = capital / current_price
                    result = place_order('buy', amount_to_buy)
                    if result:
                        position = amount_to_buy
                        capital = 0
                        trade_log.append(('Buy', current_price, capital, position))
                        send_email('XRP/USDC Buy Signal', f"Buy at {current_price:.4f} on {current_time_cet}")

                elif signal == 'Sell' and position > 0:
                    result = place_order('sell', position)
                    if result:
                        capital = position * current_price
                        position = 0
                        trade_log.append(('Sell', current_price, capital, position))
                        send_email('XRP/USDC Sell Signal', f"Sell at {current_price:.4f} on {current_time_cet}")

            time.sleep(poll_interval)
        except Exception as e:
            logger.error(f"Error in bot loop: {e}")
            send_email('Bot Error Notification', f'Error: {e} at {get_cet_time()}')
            time.sleep(60)  # Retry delay

# Streamlit App
st.title("XRP/USDC Trading Bot")

st.write("This bot trades on 5-min charts using Stochastic momentum (%K/%D crossovers), RSI for overbought/oversold, and EMA 20/50/100/200 for trend filtering. It maximizes profitability by entering only on confirmed signals with high volume.")

# Session state for bot control
if 'bot_thread' not in st.session_state:
    st.session_state.bot_thread = None
if 'stop_event' not in st.session_state:
    st.session_state.stop_event = threading.Event()

status_placeholder = st.empty()
status_placeholder.text("Bot is stopped.")

col1, col2 = st.columns(2)

with col1:
    if st.button("Start Bot"):
        if st.session_state.bot_thread is None or not st.session_state.bot_thread.is_alive():
            st.session_state.stop_event.clear()
            st.session_state.bot_thread = threading.Thread(target=trading_bot_loop, args=(st.session_state.stop_event, status_placeholder))
            st.session_state.bot_thread.start()
            st.success("Bot started!")

with col2:
    if st.button("Stop Bot"):
        if st.session_state.bot_thread and st.session_state.bot_thread.is_alive():
            st.session_state.stop_event.set()
            st.session_state.bot_thread.join()
            st.warning("Bot stopped.")

# Simple animation: Spinner while running
if st.session_state.bot_thread and st.session_state.bot_thread.is_alive():
    with st.spinner("Bot is running... Checking every 30 seconds for new 5-min candles."):
        time.sleep(1)  # Placeholder; actual loop is in thread

# Display recent logs (optional tracking)
if os.path.exists('trading_bot.log'):
    with open('trading_bot.log', 'r') as f:
        logs = f.read()
    st.text_area("Recent Logs", logs, height=200)