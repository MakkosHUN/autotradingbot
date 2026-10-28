from transformers import pipeline
import torch

# 1. Load FinBERT once when the script starts (runs 100% free on GitHub CPU)
print("Loading ProsusAI/finbert financial AI model...")
finbert = pipeline(
    "sentiment-analysis",
    model="ProsusAI/finbert",
    tokenizer="ProsusAI/finbert",
    top_k=None  # Returns all 3 probabilities: positive, negative, neutral
)

def get_finbert_sentiment(headlines):
    """
    Analyzes a list of financial headlines using ProsusAI/finbert.
    Returns a net sentiment score between -1.00 and +1.00.
    """
    if not headlines:
        return 0.0

    # Truncate headlines to 512 characters max and run batch inference
    clean_headlines = [h[:512] for h in headlines if h and len(h.strip()) > 10]
    if not clean_headlines:
        return 0.0

    results = finbert(clean_headlines)
    
    weighted_scores = []
    for res in results:
        # Convert list of dicts [{'label': 'positive', 'score': 0.85}, ...] into a clean dict
        scores = {item['label']: item['score'] for item in res}
        pos = scores.get('positive', 0.0)
        neg = scores.get('negative', 0.0)
        neu = scores.get('neutral', 0.0)
        
        # Net directional score (-1.0 to +1.0)
        net_score = pos - neg
        
        # Filter out pure fluff/neutral headlines so they don't dilute real breaking news
        if neu < 0.80:
            weighted_scores.append(net_score)
        else:
            # Give very low weight (20%) to purely neutral announcements
            weighted_scores.append(net_score * 0.2)

    if not weighted_scores:
        return 0.0

    # Calculate final average score across all fresh headlines
    final_score = sum(weighted_scores) / len(weighted_scores)
    return round(final_score, 3)
