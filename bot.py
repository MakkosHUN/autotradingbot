import alpaca_trade_api as tradeapi
from textblob import TextBlob
import time

# 1. Setup connection
BASE_URL = 'https://paper-api.alpaca.markets'
api = tradeapi.REST(base_url=BASE_URL, api_version='v2')

# Define your portfolio watchlist
SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA']
TRADE_QTY = 1
BULLISH_THRESHOLD = 0.10
BEARISH_THRESHOLD = -0.10

print("🤖 Auto-Trading Bot initialized for Portfolio Watchlist")
print("=" * 55)

for symbol in SYMBOLS:
    print(f"\n➤ Analyzing {symbol}...")
    
    # 2. Check if we already own the stock
    try:
        position = api.get_position(symbol)
        we_own_stock = True
        print(f"💼 PORTFOLIO: We own {position.qty} share(s) of {symbol}.")
    except:
        we_own_stock = False
        print(f"💼 PORTFOLIO: We do not own {symbol}.")

    # 3. Fetch news and calculate sentiment
    print(f"📡 Fetching live news articles for {symbol}...")
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

        # 4. Buy & Sell Logic
        if avg_sentiment >= BULLISH_THRESHOLD and not we_own_stock:
            print(f"🟢 Signal: BULLISH -> BUYING {symbol}")
            api.submit_order(symbol=symbol, qty=TRADE_QTY, side='buy', type='market', time_in_force='gtc')
            
        elif avg_sentiment <= BEARISH_THRESHOLD and we_own_stock:
            print(f"🔴 Signal: BEARISH -> SELLING {symbol} TO CASH OUT")
            api.close_position(symbol)
            
        else:
            print(f"🛡️ HOLD: No strong signal to change our position on {symbol}.")
            
    # 5. Respect API Rate Limits (Critical for the free plan)
    time.sleep(2)
