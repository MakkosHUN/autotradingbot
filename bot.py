import alpaca_trade_api as tradeapi
from textblob import TextBlob

# 1. Setup connection
BASE_URL = 'https://paper-api.alpaca.markets'
api = tradeapi.REST(base_url=BASE_URL, api_version='v2')

SYMBOL = 'AAPL'
TRADE_QTY = 1
BULLISH_THRESHOLD = 0.10
BEARISH_THRESHOLD = -0.10

print(f"🤖 Auto-Trading Bot initialized for: {SYMBOL}")
print("=" * 55)

# 2. Check if we already own the stock
try:
    position = api.get_position(SYMBOL)
    we_own_stock = True
    print(f"💼 PORTFOLIO: We currently own {position.qty} share(s) of {SYMBOL}.")
except:
    we_own_stock = False
    print(f"💼 PORTFOLIO: We do not currently own any shares of {SYMBOL}.")

# 3. Fetch news and calculate sentiment
print(f"📡 Fetching live news articles for {SYMBOL}...")
news_items = api.get_news(SYMBOL, limit=5)

if not news_items:
    print("No recent headlines found. Halting.")
else:
    total_polarity = 0
    valid_articles = 0

    for article in news_items:
        content = article.summary if article.summary else article.headline
        score = TextBlob(content).sentiment.polarity
        total_polarity += score
        valid_articles += 1
        print(f"  • [{score:+.2f}] {article.headline[:65]}...")

    avg_sentiment = total_polarity / valid_articles
    print("=" * 55)
    print(f"📊 Aggregated Market Sentiment: {avg_sentiment:+.3f}")

    # 4. Buy & Sell Logic
    if avg_sentiment >= BULLISH_THRESHOLD and not we_own_stock:
        print("🟢 Signal: BULLISH & We don't own it -> BUYING")
        api.submit_order(symbol=SYMBOL, qty=TRADE_QTY, side='buy', type='market', time_in_force='gtc')
        print("✅ Buy order submitted!")
        
    elif avg_sentiment <= BEARISH_THRESHOLD and we_own_stock:
        print("🔴 Signal: BEARISH & We own it -> SELLING TO CASH OUT")
        api.close_position(SYMBOL)
        print("✅ Sell order submitted! Position closed.")
        
    else:
        print("🛡️ HOLD: No strong signal to change our current position.")
