"""Place first paper order — NVDA BUY based on Pelosi signal score 72.1"""
import sys
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

from broker.ibkr_client import connect, account_summary, get_positions, disconnect
from broker.ibkr_orders import place_order, get_paper_orders
from analysis.scorer import get_top_signals

print("=== Premier ordre paper IBKR ===\n")

# Connexion
print("Connexion TWS...")
if not connect():
    print("ECHEC connexion — TWS ouvert ?")
    sys.exit(1)
print("Connecte!\n")

# Solde avant
summary = account_summary()
print(f"Solde avant ordre:")
print(f"  Cash dispo  : ${summary.get('AvailableFunds', 0):>10,.2f}")
print(f"  Liquidation : ${summary.get('NetLiquidation', 0):>10,.2f}\n")

# Meilleur signal BUY
signals = get_top_signals(20)
buy_signals = [s for s in signals if s["trade_type"] == "buy"]

if not buy_signals:
    print("Aucun signal BUY disponible, on prend NVDA directement")
    best = {"ticker": "NVDA", "score": 72.1, "politician": "Nancy Pelosi",
            "id": "test_nvda", "trade_type": "buy"}
else:
    best = buy_signals[0]

print(f"Signal selectionne:")
print(f"  Ticker    : {best['ticker']}")
print(f"  Elu       : {best['politician']}")
print(f"  Score     : {best['score']:.1f}/100")
print(f"  Signal    : {best.get('signal', 'BUY')}")
print(f"  Budget    : $2,000\n")

print(f"Passage de l'ordre BUY {best['ticker']}...")
result = place_order(
    ticker=best["ticker"],
    action="BUY",
    score=best["score"],
    politician=best["politician"],
    trade_ref=best.get("id", ""),
    budget_usd=2000,
)

print(f"\nResultat:")
for k, v in result.items():
    print(f"  {k:15s}: {v}")

# Positions apres
from broker.ibkr_client import ib
ib.sleep(2)
positions = get_positions()
print(f"\nPositions apres ordre:")
for p in positions:
    print(f"  {p['symbol']:8s} qty:{p['qty']:6.0f}  cost:${p['avg_cost']:>10,.2f}")

# Solde apres
summary2 = account_summary()
print(f"\nSolde apres ordre:")
print(f"  Cash dispo  : ${summary2.get('AvailableFunds', 0):>10,.2f}")
print(f"  Liquidation : ${summary2.get('NetLiquidation', 0):>10,.2f}")

disconnect()
print("\nOrdre place avec succes. Verifiez dans TWS onglet 'Ordres'.")
