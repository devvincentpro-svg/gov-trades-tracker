"""
Multi-source news fetcher for gov-trades-tracker.
Sources: Finnhub, Yahoo Finance, Google News RSS, GDELT, Reddit public JSON.
Sentiment via VADER (no API key, runs locally).
"""
import hashlib
import time
import re
import requests
import feedparser
import yfinance as yf
from datetime import datetime, timedelta, timezone
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from database import upsert_news, link_news_to_trades, get_conn, log_fetch
from config import FINNHUB_API_KEY, TWITTER_BEARER_TOKEN

_VADER = SentimentIntensityAnalyzer()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
}


# ─────────────────────────── helpers ────────────────────────────

def _sentiment(text: str) -> tuple[float, str]:
    score = _VADER.polarity_scores(text or "")["compound"]
    if score >= 0.05:
        return score, "positive"
    if score <= -0.05:
        return score, "negative"
    return score, "neutral"


def _article_id(url: str, ticker: str) -> str:
    return hashlib.md5(f"{ticker}|{url}".encode()).hexdigest()


def _ts_to_iso(ts) -> str:
    """Unix timestamp or datetime → ISO string."""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    return str(ts)[:16]


# ─────────────────────────── sources ────────────────────────────

def fetch_finnhub_news(ticker: str, days_back: int = 30) -> int:
    """Finnhub company news — dated, reliable."""
    if not FINNHUB_API_KEY:
        return 0
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": ticker,
                "from": start.strftime("%Y-%m-%d"),
                "to": end.strftime("%Y-%m-%d"),
                "token": FINNHUB_API_KEY,
            },
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            return 0
        articles = r.json()
    except Exception:
        return 0

    count = 0
    for a in articles:
        headline = a.get("headline", "")
        summary = a.get("summary", "")
        score, label = _sentiment(f"{headline} {summary}")
        art = {
            "id": _article_id(a.get("url", str(a.get("id", ""))), ticker),
            "ticker": ticker,
            "headline": headline,
            "summary": summary[:500],
            "url": a.get("url", ""),
            "source": f"finnhub:{a.get('source', '')}",
            "published_at": _ts_to_iso(a.get("datetime", 0)),
            "sentiment": score,
            "sentiment_label": label,
        }
        if upsert_news(art):
            count += 1
    return count


def fetch_yfinance_news(ticker: str) -> int:
    """Yahoo Finance news via yfinance — no API key needed."""
    try:
        news = yf.Ticker(ticker).news or []
    except Exception:
        return 0

    count = 0
    for a in news:
        content = a.get("content", {})
        headline = content.get("title", a.get("title", ""))
        summary = content.get("summary", "")
        url = ""
        # Extract URL from canonical or clickThroughUrl
        if isinstance(content.get("canonicalUrl"), dict):
            url = content["canonicalUrl"].get("url", "")
        if not url and isinstance(content.get("clickThroughUrl"), dict):
            url = content["clickThroughUrl"].get("url", "")
        pub_ts = content.get("pubDate") or a.get("providerPublishTime", 0)
        if isinstance(pub_ts, str):
            pub_at = pub_ts[:16]
        else:
            pub_at = _ts_to_iso(pub_ts)

        score, label = _sentiment(f"{headline} {summary}")
        art = {
            "id": _article_id(url or headline, ticker),
            "ticker": ticker,
            "headline": headline,
            "summary": summary[:500],
            "url": url,
            "source": "yahoo_finance",
            "published_at": pub_at,
            "sentiment": score,
            "sentiment_label": label,
        }
        if upsert_news(art):
            count += 1
    return count


def fetch_google_news_rss(ticker: str, extra_query: str = "") -> int:
    """Google News RSS — free, no key, rich coverage."""
    query = f"{ticker} stock {extra_query}".strip()
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
    except Exception:
        return 0

    count = 0
    for entry in feed.entries[:30]:
        headline = entry.get("title", "")
        summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))
        pub = entry.get("published", "")
        try:
            pub_dt = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M") if entry.get("published_parsed") else pub[:16]
        except Exception:
            pub_dt = pub[:16]

        score, label = _sentiment(f"{headline} {summary}")
        art = {
            "id": _article_id(entry.get("link", headline), ticker),
            "ticker": ticker,
            "headline": headline,
            "summary": summary[:500],
            "url": entry.get("link", ""),
            "source": "google_news",
            "published_at": pub_dt,
            "sentiment": score,
            "sentiment_label": label,
        }
        if upsert_news(art):
            count += 1
    return count


def fetch_gdelt_news(query: str, ticker: str, days_back: int = 30) -> int:
    """GDELT 2.0 — massive global news DB, free, no registration."""
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)
    try:
        r = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query,
                "mode": "artlist",
                "maxrecords": 25,
                "format": "json",
                "startdatetime": start.strftime("%Y%m%d%H%M%S"),
                "enddatetime": end.strftime("%Y%m%d%H%M%S"),
                "sort": "DateDesc",
            },
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            return 0
        articles = r.json().get("articles", [])
    except Exception:
        return 0

    count = 0
    for a in articles:
        headline = a.get("title", "")
        url = a.get("url", "")
        seen = a.get("seendate", "")
        # seendate format: "20240115T123456Z"
        try:
            pub_dt = datetime.strptime(seen[:15], "%Y%m%dT%H%M%S").strftime("%Y-%m-%d %H:%M")
        except Exception:
            pub_dt = seen[:16]

        score, label = _sentiment(headline)
        art = {
            "id": _article_id(url, ticker),
            "ticker": ticker,
            "headline": headline,
            "summary": "",
            "url": url,
            "source": f"gdelt:{a.get('domain', '')}",
            "published_at": pub_dt,
            "sentiment": score,
            "sentiment_label": label,
        }
        if upsert_news(art):
            count += 1
    return count


def fetch_reddit_news(ticker: str, politician: str = "") -> int:
    """Reddit public JSON API — no credentials needed for read-only."""
    queries = [ticker]
    if politician:
        queries.append(politician)

    subreddits = ["investing", "stocks", "wallstreetbets", "politics", "StockMarket"]
    count = 0

    for q in queries:
        for sub in subreddits[:3]:
            try:
                r = requests.get(
                    f"https://www.reddit.com/r/{sub}/search.json",
                    params={"q": q, "sort": "new", "limit": 15, "t": "month"},
                    headers={"User-Agent": "gov-trades-tracker/1.0"},
                    timeout=10,
                )
                if r.status_code != 200:
                    continue
                posts = r.json().get("data", {}).get("children", [])
            except Exception:
                continue

            for post in posts:
                d = post.get("data", {})
                title = d.get("title", "")
                selftext = d.get("selftext", "")[:300]
                url = f"https://reddit.com{d.get('permalink', '')}"
                created = d.get("created_utc", 0)
                score_v = d.get("score", 0)
                # Only include posts with some traction
                if score_v < 5:
                    continue

                sent_score, label = _sentiment(f"{title} {selftext}")
                art = {
                    "id": _article_id(url, ticker),
                    "ticker": ticker,
                    "headline": f"[r/{sub}] {title}",
                    "summary": selftext,
                    "url": url,
                    "source": f"reddit:r/{sub}",
                    "published_at": _ts_to_iso(created),
                    "sentiment": sent_score,
                    "sentiment_label": label,
                }
                if upsert_news(art):
                    count += 1
            time.sleep(0.5)

    return count


# ─────────────────────────── Twitter stub ────────────────────────────

def fetch_twitter_news(ticker: str, api_bearer_token: str = "") -> int:
    """
    Twitter/X API v2 — requires Bearer Token from developer.twitter.com.
    Free tier: 500K tweet reads/month. Register at developer.twitter.com,
    then set TWITTER_BEARER_TOKEN in .env.
    """
    if not api_bearer_token:
        return 0
    try:
        r = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            params={
                "query": f"${ticker} OR #{ticker} lang:en -is:retweet",
                "max_results": 50,
                "tweet.fields": "created_at,public_metrics,entities",
            },
            headers={"Authorization": f"Bearer {api_bearer_token}"},
            timeout=10,
        )
        if r.status_code != 200:
            return 0
        tweets = r.json().get("data", [])
    except Exception:
        return 0

    count = 0
    for t in tweets:
        text = t.get("text", "")
        metrics = t.get("public_metrics", {})
        engagement = metrics.get("like_count", 0) + metrics.get("retweet_count", 0)
        if engagement < 10:
            continue
        score, label = _sentiment(text)
        art = {
            "id": _article_id(t["id"], ticker),
            "ticker": ticker,
            "headline": text[:200],
            "summary": f"Likes:{metrics.get('like_count',0)} RT:{metrics.get('retweet_count',0)}",
            "url": f"https://twitter.com/i/web/status/{t['id']}",
            "source": "twitter",
            "published_at": t.get("created_at", "")[:16].replace("T", " "),
            "sentiment": score,
            "sentiment_label": label,
        }
        if upsert_news(art):
            count += 1
    return count


# ─────────────────────────── main dispatcher ────────────────────────────

def fetch_news_for_ticker(ticker: str, politician: str = "", days_back: int = 30) -> int:
    """Fetch from all sources for a single ticker."""
    if not ticker or ticker in ("", "N/A"):
        return 0

    total = 0
    total += fetch_finnhub_news(ticker, days_back)
    time.sleep(0.2)
    total += fetch_yfinance_news(ticker)
    time.sleep(0.2)
    total += fetch_google_news_rss(ticker)
    time.sleep(0.5)
    total += fetch_gdelt_news(ticker, ticker, days_back)
    time.sleep(0.5)
    total += fetch_reddit_news(ticker, politician)
    time.sleep(0.5)
    if TWITTER_BEARER_TOKEN:
        total += fetch_twitter_news(ticker, TWITTER_BEARER_TOKEN)
        time.sleep(0.5)
    return total


def fetch_all_active_tickers(days_back: int = 30) -> int:
    """Fetch news for all tickers in the trades DB — called by scheduler."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT DISTINCT t.ticker, t.politician
           FROM trades t
           WHERE t.ticker != ''
           ORDER BY t.trade_date DESC
           LIMIT 80"""
    ).fetchall()
    conn.close()

    seen_tickers = set()
    total = 0
    for ticker, politician in rows:
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        n = fetch_news_for_ticker(ticker, politician, days_back)
        total += n
        time.sleep(0.3)

    log_fetch("news_fetcher", total, "ok")
    return total
