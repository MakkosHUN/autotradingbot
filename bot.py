import alpaca_trade_api as tradeapi
from textblob import TextBlob
import time

# 1. Setup connection
BASE_URL = 'https://paper-api.alpaca.markets'
api = tradeapi.REST(base_url=BASE_URL, api_version='v2')

SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA']
TRADE_QTY = 1
BULLISH_THRESHOLD = 0.10
BEARISH_THRESHOLD = -0.10

# 2. Risk Management Rules
PROFIT_TARGET_PERCENT = 1.15  # Automatically sell and lock in profit if it goes up 15%
STOP_LOSS_PERCENT = 0.95      # Automatically sell and cut losses if it drops 5%

print("🤖 Auto-Trading Bot initialized with Risk Management")
print("=" * 55)

for symbol in SYMBOLS:
    print(f"\n➤ Analyzing {symbol}...")
    
    # 3. Check portfolio
    try:
        position = api.get_position(symbol)
        we_own_stock = True
        print(f"💼 PORTFOLIO: We own {position.qty} share(s) of {symbol}.")
    except:
        we_own_stock = False
        print(f"💼 PORTFOLIO: We do not own {symbol}.")

    # 4. Fetch news
    news_items = api.get_news(symbol, limit=5)

    if not news_items:
        print(f"No recent headlines found for {symbol}. Skipping.")
    else:
        total_polarity = 0
        valid_articles = 0

        for article in news_items:
            content = article.summary if article.summary else article.headline
            score = TextBlob(content).sentiment.polarity
            total_polarity += score
            valid_articles += 1

        avg_sentiment = total_polarity / valid_articles
        print(f"📊 Aggregated Market Sentiment: {avg_sentiment:+.3f}")

        # 5. Buy & Sell Logic with Bracket Orders
        if avg_sentiment >= BULLISH_THRESHOLD and not we_own_stock:
            print(f"🟢 Signal: BULLISH -> BUYING {symbol} with Bracket Order")
            
            # Fetch the live price of the stock right now
            latest_trade = api.get_latest_trade(symbol)
            current_price = latest_trade.price
            
            # Calculate the exact dollar amounts for our safety nets
            target_price = round(current_price * PROFIT_TARGET_PERCENT, 2)
            stop_price = round(current_price * STOP_LOSS_PERCENT, 2)
            
            print(f"🛡️ Safety Nets: Take-Profit at ${target_price} \vert{} Stop-Loss at${stop_price}")
            
            # Submit the master order with attached safety nets
            api.submit_order(
                symbol=symbol,
                qty=TRADE_QTY,
                side='buy',
                type='market',
                time_in_force='gtc',
                order_class='bracket',
                take_profit={'limit_price': target_price},
                stop_loss={'stop_price': stop_price}
            )
            
        elif avg_sentiment <= BEARISH_THRESHOLD and we_own_stock:
            print(f"🔴 Signal: BEARISH -> SELLING {symbol} TO CASH OUT")
            api.close_position(symbol)
