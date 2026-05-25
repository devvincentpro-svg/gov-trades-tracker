"""
IBKR TWS connection manager using ib_insync.
Paper trading: port 7497. Live: port 7496.
Call connect() once at startup; the IB object is shared across modules.
"""
import logging
from ib_insync import IB, util

log = logging.getLogger(__name__)

# Shared IB instance — import from here in all other broker modules
ib = IB()

TWS_HOST = "127.0.0.1"
TWS_PORT = 7497          # paper trading
CLIENT_ID = 10           # unique ID per connection (change if conflict)


def connect(host: str = TWS_HOST, port: int = TWS_PORT, client_id: int = CLIENT_ID) -> bool:
    """Connect to TWS. Returns True if successful."""
    if ib.isConnected():
        return True
    try:
        util.startLoop()  # needed in non-async context
        ib.connect(host, port, clientId=client_id, timeout=10)
        acc = ib.managedAccounts()
        log.info(f"IBKR connected — accounts: {acc}")
        print(f"IBKR connecte — comptes: {acc}")
        return True
    except Exception as e:
        log.error(f"IBKR connection failed: {e}")
        print(f"IBKR connexion echouee: {e}")
        return False


def disconnect():
    if ib.isConnected():
        ib.disconnect()


def is_connected() -> bool:
    return ib.isConnected()


def account_summary() -> dict:
    """Return key portfolio metrics from the paper account."""
    if not ib.isConnected():
        return {}
    summary = ib.accountSummary()
    result = {}
    for item in summary:
        if item.tag in ("NetLiquidation", "TotalCashValue", "UnrealizedPnL",
                        "RealizedPnL", "GrossPositionValue", "AvailableFunds"):
            result[item.tag] = float(item.value) if item.value else 0.0
    return result


def get_positions() -> list[dict]:
    """Return all open positions in the paper account."""
    if not ib.isConnected():
        return []
    positions = ib.positions()
    result = []
    for p in positions:
        result.append({
            "symbol": p.contract.symbol,
            "qty": p.position,
            "avg_cost": round(p.avgCost, 2),
            "market_value": round(p.marketValue if hasattr(p, "marketValue") else 0, 2),
        })
    return result
