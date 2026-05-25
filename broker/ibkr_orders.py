"""
Paper trading order execution via IBKR TWS.
Places market or limit orders, tracks fills, logs everything to DB.
ALWAYS operates on the paper account (port 7497).
"""
import logging
from datetime import datetime
from ib_insync import Stock, MarketOrder, LimitOrder, StopOrder

from broker.ibkr_client import ib, is_connected
from database import get_conn

log = logging.getLogger(__name__)

# Max position size per trade (paper trading safety)
MAX_POSITION_USD = 10_000
DEFAULT_STOP_PCT = 0.05     # 5% stop-loss
DEFAULT_TARGET_PCT = 0.15   # 15% take-profit


def _init_orders_table():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_orders (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT NOT NULL,
            action       TEXT NOT NULL,
            qty          INTEGER,
            order_type   TEXT,
            limit_price  REAL,
            fill_price   REAL,
            status       TEXT,
            signal_score REAL,
            politician   TEXT,
            trade_ref    TEXT,
            placed_at    TEXT DEFAULT (datetime('now')),
            filled_at    TEXT,
            pnl          REAL
        );
    """)
    conn.commit()
    conn.close()


_init_orders_table()


def place_order(
    ticker: str,
    action: str,          # "BUY" or "SELL"
    score: float,         # 0-100 signal score
    politician: str = "",
    trade_ref: str = "",
    budget_usd: float = MAX_POSITION_USD,
) -> dict:
    """
    Place a paper market order sized by score and budget.
    score 90-100 → full budget, 70-90 → 60%, 50-70 → 30%
    Adds a stop-loss bracket automatically.
    """
    if not is_connected():
        log.error("IBKR not connected — order aborted")
        return {"status": "error", "reason": "not connected"}

    # Size position by conviction score
    if score >= 90:
        size_pct = 1.0
    elif score >= 75:
        size_pct = 0.6
    else:
        size_pct = 0.3
    budget = budget_usd * size_pct

    # Get current price to calculate qty
    try:
        contract = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(contract)
        mkt_data = ib.reqMktData(contract, "", True, False)
        ib.sleep(1.5)
        ib.cancelMktData(contract)
        import math
        raw_price = mkt_data.last or mkt_data.close or 0
        price = raw_price if (raw_price and not math.isnan(raw_price)) else 0

        # Fallback 1: our own prices DB (most recent close)
        if price <= 0:
            try:
                conn_p = get_conn()
                row = conn_p.execute(
                    "SELECT price FROM prices WHERE ticker=? ORDER BY fetched_at DESC LIMIT 1",
                    (ticker,)
                ).fetchone()
                conn_p.close()
                if row and row[0]:
                    price = float(row[0])
            except Exception:
                pass

        # Fallback 2: Finnhub quote
        if price <= 0:
            try:
                import requests as req
                from config import FINNHUB_API_KEY
                r = req.get("https://finnhub.io/api/v1/quote",
                            params={"symbol": ticker, "token": FINNHUB_API_KEY}, timeout=5)
                if r.status_code == 200:
                    price = float(r.json().get("c") or 0)
            except Exception:
                pass

        # Fallback 3: yfinance (works on weekdays)
        if price <= 0:
            import yfinance as yf
            try:
                hist = yf.Ticker(ticker).history(period="5d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            except Exception:
                pass

        if price <= 0:
            return {"status": "error", "reason": f"no price available for {ticker} (market closed?)"}

        qty = max(1, int(budget / price))

        # Main market order
        order = MarketOrder(action, qty)
        trade = ib.placeOrder(contract, order)
        ib.sleep(1.0)

        fill_price = trade.orderStatus.avgFillPrice or price
        status = trade.orderStatus.status

        # Stop-loss bracket
        if action == "BUY" and status in ("Filled", "Submitted", "PreSubmitted"):
            stop_price = round(fill_price * (1 - DEFAULT_STOP_PCT), 2)
            target_price = round(fill_price * (1 + DEFAULT_TARGET_PCT), 2)
            stop_order = StopOrder("SELL", qty, stop_price)
            stop_order.parentId = trade.order.orderId
            ib.placeOrder(contract, stop_order)
            log.info(f"Stop-loss set at ${stop_price} for {ticker}")

        # Log to DB
        conn = get_conn()
        conn.execute(
            """INSERT INTO paper_orders
               (ticker, action, qty, order_type, fill_price, status,
                signal_score, politician, trade_ref, filled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, action, qty, "MKT", round(fill_price, 2), status,
             score, politician, trade_ref, datetime.utcnow().strftime("%Y-%m-%d %H:%M")),
        )
        conn.commit()
        conn.close()

        result = {
            "status": status,
            "ticker": ticker,
            "action": action,
            "qty": qty,
            "fill_price": round(fill_price, 2),
            "total_usd": round(fill_price * qty, 2),
            "score": score,
            "politician": politician,
        }
        log.info(f"Order placed: {result}")
        return result

    except Exception as e:
        log.error(f"Order error for {ticker}: {e}")
        return {"status": "error", "reason": str(e)}


def close_position(ticker: str, reason: str = "manual") -> dict:
    """Close all open position for a ticker."""
    if not is_connected():
        return {"status": "error", "reason": "not connected"}
    try:
        positions = ib.positions()
        for pos in positions:
            if pos.contract.symbol == ticker and pos.position != 0:
                contract = Stock(ticker, "SMART", "USD")
                ib.qualifyContracts(contract)
                action = "SELL" if pos.position > 0 else "BUY"
                order = MarketOrder(action, abs(pos.position))
                trade = ib.placeOrder(contract, order)
                ib.sleep(1.0)
                return {
                    "status": trade.orderStatus.status,
                    "ticker": ticker,
                    "qty": abs(pos.position),
                    "reason": reason,
                }
        return {"status": "no_position", "ticker": ticker}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def get_paper_orders(limit: int = 50) -> list[dict]:
    """Load paper order history from DB."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM paper_orders ORDER BY placed_at DESC LIMIT ?", (limit,)
    ).fetchall()
    cols = [d[0] for d in conn.execute("PRAGMA table_info(paper_orders)").fetchall()]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]
