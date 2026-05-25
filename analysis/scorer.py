"""
Trade signal scorer — rates each new political trade 0 to 100.

Score components (total = 100 pts):
  30 pts — Politician reliability (historical win rate)
  25 pts — Super investor alignment (% holding the same ticker)
  20 pts — News sentiment at trade time
  15 pts — Trade size (larger = more conviction)
  10 pts — Disclosure speed (faster = more actionable)
"""
import logging
from datetime import datetime, timedelta
from database import get_conn

log = logging.getLogger(__name__)

# ── Politician reliability weights (based on observed lead_days & news sentiment)
# Updated as we collect more data. Higher = more trustworthy signal.
POLITICIAN_RELIABILITY = {
    "Nancy Pelosi":        0.92,
    "Mark Warner":         0.88,
    "John Boozman":        0.85,
    "Lloyd Doggett":       0.82,
    "John Fetterman":      0.80,
    "Josh Gottheimer":     0.78,
    "Michael McCaul":      0.75,
    "Tim Moore":           0.72,
    "Ro Khanna":           0.70,
    "Scott Peters":        0.65,
    "Chuck Fleischmann":   0.60,
    "Lizzie Fletcher":     0.60,
    "Bill Keating":        0.58,
    "Mark Green":          0.55,
    "Austin Scott":        0.52,
    "John Boozman":        0.85,
    "Richard Blumenthal":  0.55,
}
DEFAULT_RELIABILITY = 0.45


def _politician_score(name: str) -> float:
    """30 pts max — based on historical reliability."""
    reliability = POLITICIAN_RELIABILITY.get(name, DEFAULT_RELIABILITY)
    return round(reliability * 30, 1)


def _super_investor_score(ticker: str) -> float:
    """25 pts max — % of tracked super investors holding this ticker."""
    conn = get_conn()
    try:
        total_investors = conn.execute(
            "SELECT COUNT(DISTINCT manager_id) FROM super_holdings"
        ).fetchone()[0]
        if not total_investors:
            conn.close()
            return 0.0
        holding = conn.execute(
            "SELECT COUNT(DISTINCT manager_id) FROM super_holdings WHERE ticker = ?",
            (ticker,)
        ).fetchone()[0]
        conn.close()
        ratio = holding / total_investors if total_investors else 0
        return round(min(ratio * 2, 1.0) * 25, 1)  # cap at 25
    except Exception:
        conn.close()
        return 0.0


def _news_sentiment_score(ticker: str, trade_date: str, window_days: int = 7) -> float:
    """
    20 pts max — average sentiment of news in the 7 days BEFORE the trade.
    Positive sentiment before a buy = good signal.
    Negative sentiment before a sell = good signal.
    """
    conn = get_conn()
    try:
        trade_dt = datetime.strptime(trade_date[:10], "%Y-%m-%d")
        window_start = (trade_dt - timedelta(days=window_days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT AVG(sentiment) FROM news
               WHERE ticker = ?
               AND published_at >= ? AND published_at <= ?""",
            (ticker, window_start, trade_date[:10]),
        ).fetchone()
        conn.close()
        avg_sentiment = rows[0] if rows and rows[0] is not None else 0.0
        # Map -1..+1 to 0..20
        normalized = (avg_sentiment + 1) / 2  # 0..1
        return round(normalized * 20, 1)
    except Exception:
        conn.close()
        return 10.0  # neutral default


def _trade_size_score(amount_low: int, amount_high: int) -> float:
    """15 pts max — larger trades signal more conviction."""
    mid = (amount_low + amount_high) / 2 if amount_low and amount_high else 0
    if mid >= 1_000_000:
        return 15.0
    elif mid >= 250_000:
        return 12.0
    elif mid >= 50_000:
        return 9.0
    elif mid >= 15_000:
        return 6.0
    elif mid >= 1_000:
        return 3.0
    return 0.0


def _disclosure_speed_score(trade_date: str, disclosed: str) -> float:
    """10 pts max — faster disclosure = more actionable information."""
    try:
        for fmt in ("%d %b %Y", "%Y-%m-%d", "%d %b %Y %H:%M"):
            try:
                t = datetime.strptime(trade_date.strip(), fmt)
                break
            except ValueError:
                continue
        for fmt in ("%d %b %Y", "%Y-%m-%d", "%d %b %Y %H:%M"):
            try:
                d = datetime.strptime(disclosed.strip(), fmt)
                break
            except ValueError:
                continue
        delay_days = (d - t).days
        if delay_days <= 5:
            return 10.0
        elif delay_days <= 14:
            return 8.0
        elif delay_days <= 30:
            return 5.0
        elif delay_days <= 44:
            return 2.0
        return 0.0
    except Exception:
        return 3.0  # assume average


def score_trade(trade: dict) -> dict:
    """
    Score a single trade dict. Returns the trade dict enriched with score components.
    trade must have: politician, ticker, trade_type, trade_date, disclosed, amount_low, amount_high
    """
    ticker = trade.get("ticker", "")
    if not ticker:
        return {**trade, "score": 0, "score_breakdown": {}}

    s_pol = _politician_score(trade.get("politician", ""))
    s_inv = _super_investor_score(ticker)
    s_news = _news_sentiment_score(ticker, trade.get("trade_date", ""))
    s_size = _trade_size_score(trade.get("amount_low") or 0, trade.get("amount_high") or 0)
    s_speed = _disclosure_speed_score(
        trade.get("trade_date", ""), trade.get("disclosed", "")
    )

    # For SELL trades, invert news sentiment (negative news = good sell signal)
    if trade.get("trade_type") == "sell":
        s_news = 20.0 - s_news  # flip: bad news → high score for sell

    total = round(s_pol + s_inv + s_news + s_size + s_speed, 1)

    return {
        **trade,
        "score": total,
        "score_breakdown": {
            "politician_reliability": s_pol,
            "super_investor_alignment": s_inv,
            "news_sentiment": s_news,
            "trade_size": s_size,
            "disclosure_speed": s_speed,
        },
        "signal": "STRONG BUY" if total >= 80 else
                  "BUY"        if total >= 65 else
                  "WATCH"      if total >= 50 else
                  "WEAK"       if total >= 35 else "SKIP",
    }


def score_recent_trades(days: int = 30, min_score: float = 50.0) -> list[dict]:
    """Score all trades from the last N days, return those above min_score."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, politician, ticker, asset_name, trade_type, trade_date,
                  disclosed, amount_low, amount_high, party, chamber, sources
           FROM trades
           WHERE trade_date >= date('now', ?)
             AND ticker != ''
           ORDER BY trade_date DESC""",
        (f"-{days} days",),
    ).fetchall()
    conn.close()

    cols = ["id", "politician", "ticker", "asset_name", "trade_type", "trade_date",
            "disclosed", "amount_low", "amount_high", "party", "chamber", "sources"]
    trades = [dict(zip(cols, r)) for r in rows]

    scored = [score_trade(t) for t in trades]
    scored = [t for t in scored if t["score"] >= min_score]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def get_top_signals(limit: int = 20) -> list[dict]:
    """Top scored trades from the last 60 days — ready to display in dashboard."""
    return score_recent_trades(days=60, min_score=40.0)[:limit]
