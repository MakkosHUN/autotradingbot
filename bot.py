import alpaca_trade_api as tradeapi
from textblob import TextBlob
import os

# 1. Connect using hidden GitHub Secrets
API_KEY = os.environ.get('PKWYV456U5OTMCW3IY3XIIXVT6')
SECRET_KEY = os.environ.get('AsFsMAeisVkLoxSKJCMnXAPGWkEfGGwpygc9kJjEgUkG')
BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(API_KEY, SECRET_KEY, BASE_URL, api_version='v2')

# 2. Configuration & Target Asset
SYMBOL = 'AAPL'
TRADE_QTY = 1
BULLISH_THRESHOLD = 0.10   

print(f"🤖 Auto-Trading Bot initialized for: {SYMBOL}")
print("=" * 55)

# 3. Pipeline: Fetch the latest market news
print(f"📡 Fetching live news articles for {SYMBOL}...")
news_items = api.get_news(SYMBOL, limit=5)

if not news_items:
    print("No recent headlines found. Halting execution.")
else:
    # 4. AI Engine: Quantify sentiment across all articles
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

    # 5. Decision & Execution Logic
    if avg_sentiment >= BULLISH_THRESHOLD:
        print(f"🟢 Signal: BULLISH")
        try:
            order = api.submit_order(
                symbol=SYMBOL, qty=TRADE_QTY, side='buy', type='market', time_in_force='gtc'
            )
            print(f"✅ Order submitted successfully! (Order ID: {order.id})")
        except Exception as err:
            print(f"❌ Execution error: {err}")
    else:
        print("🛡️ Condition not met. Preserving capital, no trade placed.")
