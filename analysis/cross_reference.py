"""
Cross-reference political trades with super investor holdings.
Matching strategy: ticker (direct) > issuer name fuzzy match (via ticker_info).
"""
from database import get_conn


def get_alignment(ticker: str) -> list[dict]:
    """Return list of super investors holding this ticker, with portfolio %."""
    if not ticker:
        return []
    conn = get_conn()

    # Direct match by ticker (Dataroma stores tickers directly)
    rows = conn.execute(
        """SELECT si.name, sh.pct_port, sh.value_usd, sh.shares, sh.activity, sh.quarter, sh.source
           FROM super_holdings sh
           JOIN super_investors si ON sh.manager_id = si.manager_id
           WHERE sh.ticker = ?
           ORDER BY sh.value_usd DESC""",
        (ticker.upper(),),
    ).fetchall()

    # Fallback: match via cusip_map issuer name → ticker_info
    if not rows:
        issuer_rows = conn.execute(
            """SELECT si.name, sh.pct_port, sh.value_usd, sh.shares, sh.activity, sh.quarter, sh.source
               FROM super_holdings sh
               JOIN super_investors si ON sh.manager_id = si.manager_id
               JOIN cusip_map cm ON sh.ticker = cm.cusip
               JOIN ticker_info ti ON LOWER(ti.name) LIKE '%' || LOWER(SUBSTR(cm.issuer,1,10)) || '%'
               WHERE ti.ticker = ?
               ORDER BY sh.value_usd DESC""",
            (ticker.upper(),),
        ).fetchall()
        rows = issuer_rows

    conn.close()
    return [
        {
            "investor": r[0], "pct_port": r[1], "value_usd": r[2],
            "shares": r[3], "activity": r[4], "quarter": r[5], "source": r[6],
        }
        for r in rows
    ]


def alignment_score(ticker: str) -> float:
    """0-100 score: how many super investors hold this ticker."""
    conn = get_conn()
    total_investors = conn.execute("SELECT COUNT(DISTINCT manager_id) FROM super_investors").fetchone()[0] or 1
    holders = len(get_alignment(ticker))
    conn.close()
    return round(holders / total_investors * 100, 1)


def get_top_aligned_trades(limit: int = 20) -> list[dict]:
    """Return political trades most aligned with super investor holdings."""
    conn = get_conn()
    trades = conn.execute(
        """SELECT DISTINCT t.ticker, t.politician, t.trade_type, t.trade_date,
                  CAST((COALESCE(t.amount_low,0) + COALESCE(t.amount_high,0)) / 2 AS INTEGER) as amount_mid
           FROM trades t
           WHERE t.ticker != ''
           ORDER BY t.trade_date DESC
           LIMIT 200"""
    ).fetchall()
    conn.close()

    results = []
    for ticker, politician, trade_type, trade_date, amount_mid in trades:
        investors = get_alignment(ticker)
        if investors:
            results.append({
                "ticker": ticker,
                "politician": politician,
                "trade_type": trade_type,
                "trade_date": trade_date,
                "amount_mid": amount_mid,
                "super_investors_count": len(investors),
                "top_investor": investors[0]["investor"] if investors else "",
                "alignment_score": alignment_score(ticker),
            })

    results.sort(key=lambda x: x["super_investors_count"], reverse=True)
    return results[:limit]


def get_shared_tickers() -> list[dict]:
    """Tickers held by both politicians (recently traded) and super investors."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT t.ticker, COUNT(DISTINCT t.politician) as pol_count,
                  COUNT(DISTINCT sh.manager_id) as inv_count,
                  SUM((COALESCE(t.amount_low,0)+COALESCE(t.amount_high,0))/2) as pol_volume
           FROM trades t
           JOIN super_holdings sh ON sh.ticker = t.ticker
           WHERE t.ticker != ''
           GROUP BY t.ticker
           ORDER BY inv_count DESC, pol_count DESC
           LIMIT 50"""
    ).fetchall()
    conn.close()
    return [
        {"ticker": r[0], "politicians": r[1], "super_investors": r[2], "pol_volume": r[3]}
        for r in rows
    ]
