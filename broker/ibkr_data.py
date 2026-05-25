"""
Real-time and historical market data from IBKR TWS.
Falls back to yfinance if TWS is not connected.
"""
import logging
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from ib_insync import Stock, util

from broker.ibkr_client import ib, is_connected

log = logging.getLogger(__name__)


def _stock(ticker: str):
    return Stock(ticker, "SMART", "USD")


def get_live_price(ticker: str) -> dict:
    """Fetch real-time snapshot: price, bid, ask, volume."""
    if not is_connected():
        return _yf_fallback(ticker)
    try:
        contract = _stock(ticker)
        ib.qualifyContracts(contract)
        ticker_obj = ib.reqMktData(contract, "", True, False)
        ib.sleep(1.5)
        ib.cancelMktData(contract)
        return {
            "ticker": ticker,
            "price": ticker_obj.last or ticker_obj.close or 0.0,
            "bid": ticker_obj.bid or 0.0,
            "ask": ticker_obj.ask or 0.0,
            "volume": ticker_obj.volume or 0,
            "change_pct": round(
                ((ticker_obj.last or 0) - (ticker_obj.close or 1)) / (ticker_obj.close or 1) * 100, 2
            ),
            "source": "ibkr",
            "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        log.warning(f"IBKR live price failed for {ticker}: {e}")
        return _yf_fallback(ticker)


def get_historical(ticker: str, days: int = 365, bar_size: str = "1 day") -> pd.DataFrame:
    """
    Fetch OHLCV history from IBKR.
    bar_size options: '1 min', '5 mins', '1 hour', '1 day'
    """
    if not is_connected():
        return _yf_history(ticker, days)
    try:
        contract = _stock(ticker)
        ib.qualifyContracts(contract)
        duration = f"{min(days, 365)} D" if days <= 365 else f"{days // 365} Y"
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        if not bars:
            return _yf_history(ticker, days)
        df = util.df(bars)
        df = df.rename(columns={"date": "Date", "open": "Open", "high": "High",
                                 "low": "Low", "close": "Close", "volume": "Volume"})
        df["ticker"] = ticker
        return df
    except Exception as e:
        log.warning(f"IBKR history failed for {ticker}: {e}")
        return _yf_history(ticker, days)


def get_bulk_prices(tickers: list[str]) -> list[dict]:
    """Fetch live prices for multiple tickers."""
    results = []
    for ticker in tickers:
        data = get_live_price(ticker)
        if data:
            results.append(data)
    return results


# ── yfinance fallbacks ──────────────────────────────────────

def _yf_fallback(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = info.get("last_price", 0) or 0
        prev = info.get("previous_close", price) or price
        change = round((price - prev) / prev * 100, 2) if prev else 0
        return {
            "ticker": ticker,
            "price": round(price, 2),
            "bid": 0.0, "ask": 0.0,
            "volume": int(info.get("three_month_average_volume", 0) or 0),
            "change_pct": change,
            "source": "yfinance",
            "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception:
        return {"ticker": ticker, "price": 0.0, "source": "error",
                "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M")}


def _yf_history(ticker: str, days: int = 365) -> pd.DataFrame:
    try:
        period = f"{min(days, 730)}d"
        df = yf.download(ticker, period=period, progress=False)
        df["ticker"] = ticker
        return df.reset_index()
    except Exception:
        return pd.DataFrame()
