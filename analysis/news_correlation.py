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
    For each trade with a ticker, link it to nearby news:
    - Positive lead_days: news came AFTER the trade (politician was ahead)
    - Negative lead_days: news came BEFORE the trade (politician reacted)
    Window spans [-window_days, +window_days] around the trade date.
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

        window_start = trade_dt - timedelta(days=7)   # 7 days before (reacting to news)
        window_end = trade_dt + timedelta(days=window_days)   # window_days after

        news_rows = conn.execute(
            """SELECT id, published_at, sentiment FROM news
               WHERE ticker = ?
               AND published_at >= ?
               AND published_at <= ?
               AND ABS(sentiment) >= 0.05""",
            (
                ticker,
                window_start.strftime("%Y-%m-%d"),
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
    One row per trade (the most significant news after the trade).
    Sorted by lead_days desc (most anticipatory first).
    """
    conn = get_conn()
    rows = conn.execute(
        """WITH ranked_news AS (
               -- For each trade, pick the FIRST significant news after it (min lead_days)
               SELECT
                   nt.trade_id,
                   nt.lead_days,
                   n.headline, n.source, n.published_at, n.sentiment, n.sentiment_label, n.url,
                   ROW_NUMBER() OVER (PARTITION BY nt.trade_id ORDER BY nt.lead_days ASC) AS rn
               FROM news_trades nt
               JOIN news n ON n.id = nt.news_id
               WHERE nt.lead_days >= ?
                 AND ABS(n.sentiment) >= 0.1
           )
           SELECT
               t.politician, t.ticker, t.asset_name, t.trade_type, t.trade_date,
               t.party, t.chamber,
               (COALESCE(t.amount_low,0)+COALESCE(t.amount_high,0))/2 AS amount,
               rn.lead_days,
               rn.headline, rn.source, rn.published_at, rn.sentiment, rn.sentiment_label, rn.url
           FROM ranked_news rn
           JOIN trades t ON t.id = rn.trade_id
           WHERE rn.rn = 1
           ORDER BY rn.lead_days DESC
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
    Aggregates per-trade first (min lead_days per trade) to avoid multi-article bias.
    Higher avg_lead_days = consistently ahead of news cycle.
    """
    conn = get_conn()
    rows = conn.execute(
        """WITH trade_lead AS (
               -- For each trade, take the MINIMUM lead time (= the first news that came out)
               -- and the average sentiment of news following the trade
               SELECT
                   nt.trade_id,
                   MIN(nt.lead_days)    AS first_news_lead,
                   AVG(n.sentiment)     AS trade_sentiment
               FROM news_trades nt
               JOIN news n ON n.id = nt.news_id AND ABS(n.sentiment) >= 0.05
               WHERE nt.lead_days >= 0
               GROUP BY nt.trade_id
           )
           SELECT
               t.politician, t.party, t.chamber,
               COUNT(DISTINCT t.id)                                     AS total_trades,
               COUNT(tl.trade_id)                                       AS trades_with_news,
               AVG(tl.first_news_lead)                                  AS avg_lead_days,
               COUNT(CASE WHEN tl.first_news_lead > 3 THEN 1 END)      AS trades_ahead,
               AVG(tl.trade_sentiment)                                  AS avg_news_sentiment
           FROM trades t
           LEFT JOIN trade_lead tl ON tl.trade_id = t.id
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
