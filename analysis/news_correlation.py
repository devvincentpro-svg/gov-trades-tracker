"""
Cross-reference political trades with news events.
Key question: did politicians trade BEFORE significant news broke?
lead_days = news_published_at - trade_date  (positive = politician was AHEAD)
"""
from datetime import datetime, timedelta
import pandas as pd
from database import get_conn, link_news_to_trades


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d %b %Y", "%d %b %Y %H:%M"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except ValueError:
            continue
    return None


def compute_lead_times(window_days: int = 30) -> int:
    """
    For each trade with a ticker, find news published in the next `window_days` days.
    Store lead_days in news_trades table. Returns number of links created.
    """
    conn = get_conn()
    trades = conn.execute(
        "SELECT id, ticker, trade_date FROM trades WHERE ticker != '' AND trade_date != ''"
    ).fetchall()

    count = 0
    for trade_id, ticker, trade_date_raw in trades:
        trade_dt = _parse_date(trade_date_raw)
        if not trade_dt:
            continue

        window_end = trade_dt + timedelta(days=window_days)
        news_rows = conn.execute(
            """SELECT id, published_at, sentiment FROM news
               WHERE ticker = ?
               AND published_at >= ?
               AND published_at <= ?
               AND ABS(sentiment) >= 0.05""",
            (
                ticker,
                trade_dt.strftime("%Y-%m-%d"),
                window_end.strftime("%Y-%m-%d"),
            ),
        ).fetchall()

        for news_id, pub_raw, _ in news_rows:
            pub_dt = _parse_date(pub_raw)
            if not pub_dt:
                continue
            lead_days = (pub_dt - trade_dt).total_seconds() / 86400
            link_news_to_trades(news_id, trade_id, round(lead_days, 1))
            count += 1

    conn.close()
    return count


def get_advance_trades(min_lead_days: float = 3.0, limit: int = 50) -> list[dict]:
    """
    Trades where politician acted at least `min_lead_days` before significant news.
    Returns sorted by lead_days desc (most anticipatory first).
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT
               t.politician, t.ticker, t.asset_name, t.trade_type, t.trade_date,
               t.party, t.chamber,
               (COALESCE(t.amount_low,0)+COALESCE(t.amount_high,0))/2 AS amount,
               nt.lead_days,
               n.headline, n.source, n.published_at, n.sentiment, n.sentiment_label, n.url
           FROM news_trades nt
           JOIN trades t ON t.id = nt.trade_id
           JOIN news n   ON n.id = nt.news_id
           WHERE nt.lead_days >= ?
             AND ABS(n.sentiment) >= 0.1
           ORDER BY nt.lead_days DESC
           LIMIT ?""",
        (min_lead_days, limit),
    ).fetchall()
    conn.close()

    cols = ["politician", "ticker", "asset_name", "trade_type", "trade_date",
            "party", "chamber", "amount", "lead_days",
            "headline", "source", "published_at", "sentiment", "sentiment_label", "url"]
    return [dict(zip(cols, r)) for r in rows]


def get_politician_timing_stats() -> list[dict]:
    """
    Per-politician: avg lead days, % trades before significant news, count.
    Higher avg_lead_days = consistently ahead of news cycle.
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT
               t.politician, t.party, t.chamber,
               COUNT(DISTINCT t.id)             AS total_trades,
               COUNT(DISTINCT nt.trade_id)      AS trades_with_news,
               AVG(nt.lead_days)                AS avg_lead_days,
               SUM(CASE WHEN nt.lead_days > 3 THEN 1 ELSE 0 END) AS trades_ahead,
               AVG(n.sentiment)                 AS avg_news_sentiment
           FROM trades t
           LEFT JOIN news_trades nt ON nt.trade_id = t.id
           LEFT JOIN news n         ON n.id = nt.news_id AND ABS(n.sentiment) >= 0.1
           WHERE t.ticker != ''
           GROUP BY t.politician
           HAVING trades_with_news > 0
           ORDER BY avg_lead_days DESC""",
    ).fetchall()
    conn.close()

    cols = ["politician", "party", "chamber", "total_trades", "trades_with_news",
            "avg_lead_days", "trades_ahead", "avg_news_sentiment"]
    return [dict(zip(cols, r)) for r in rows]


def get_ticker_sentiment_timeline(ticker: str) -> pd.DataFrame:
    """Sentiment over time for a ticker — for the dashboard chart."""
    conn = get_conn()
    df = pd.read_sql_query(
        """SELECT published_at, sentiment, sentiment_label, headline, source
           FROM news
           WHERE ticker = ?
           ORDER BY published_at""",
        conn, params=(ticker,)
    )
    conn.close()
    if df.empty:
        return df
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
    df = df.dropna(subset=["published_at"])
    return df


def get_news_for_ticker(ticker: str, limit: int = 20) -> list[dict]:
    """Recent news for a ticker, newest first."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT headline, source, published_at, sentiment, sentiment_label, url
           FROM news WHERE ticker = ?
           ORDER BY published_at DESC LIMIT ?""",
        (ticker, limit),
    ).fetchall()
    conn.close()
    cols = ["headline", "source", "published_at", "sentiment", "sentiment_label", "url"]
    return [dict(zip(cols, r)) for r in rows]


def get_sentiment_vs_trades(ticker: str) -> pd.DataFrame:
    """
    Combined DataFrame: trade events + news sentiment for a ticker.
    Used to build the timeline chart showing trades vs news reaction.
    """
    conn = get_conn()
    trades_df = pd.read_sql_query(
        """SELECT trade_date as date, politician, trade_type,
                  (COALESCE(amount_low,0)+COALESCE(amount_high,0))/2 as amount
           FROM trades WHERE ticker = ? AND trade_date != ''""",
        conn, params=(ticker,)
    )
    news_df = pd.read_sql_query(
        """SELECT published_at as date, headline, sentiment, sentiment_label, source
           FROM news WHERE ticker = ?""",
        conn, params=(ticker,)
    )
    conn.close()

    trades_df["type"] = "trade"
    news_df["type"] = "news"
    trades_df["date"] = pd.to_datetime(trades_df["date"], errors="coerce")
    news_df["date"] = pd.to_datetime(news_df["date"], errors="coerce")
    return trades_df, news_df
