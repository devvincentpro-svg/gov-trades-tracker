import yfinance as yf
from database import upsert_price, get_conn


def get_active_tickers() -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM trades WHERE ticker != '' ORDER BY trade_date DESC LIMIT 100"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]


def fetch_prices(tickers: list[str] | None = None):
    if tickers is None:
        tickers = get_active_tickers()
    if not tickers:
        return

    batch = " ".join(tickers)
    try:
        data = yf.download(batch, period="1d", interval="15m", progress=False, group_by="ticker")
    except Exception:
        return

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                df = data
            else:
                df = data[ticker]
            if df.empty:
                continue
            last = df.iloc[-1]
            first = df.iloc[0]
            price = float(last["Close"])
            change_pct = ((price - float(first["Open"])) / float(first["Open"])) * 100
            upsert_price(ticker, round(price, 2), round(change_pct, 2))
        except Exception:
            continue
