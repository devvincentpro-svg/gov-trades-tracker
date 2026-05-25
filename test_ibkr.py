"""Test IBKR TWS connection + scoring engine."""
import sys
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

print("=== Test connexion IBKR TWS (Paper Trading) ===")
print("Tentative connexion sur 127.0.0.1:7497 ...")

from broker.ibkr_client import connect, account_summary, get_positions, disconnect

ok = connect()
if not ok:
    print("\nECHEC — Verifiez que TWS est ouvert en Paper Trading")
    print("et que l'API est activee (Edit > Global Configuration > API > Settings)")
    sys.exit(1)

print("\nConnexion reussie!")

print("\n--- Compte Paper ---")
summary = account_summary()
for k, v in summary.items():
    print(f"  {k:25s}: ${v:>15,.2f}")

print("\n--- Positions ouvertes ---")
positions = get_positions()
if positions:
    for p in positions:
        print(f"  {p['symbol']:8s} qty:{p['qty']:6.0f}  cost:${p['avg_cost']:>10,.2f}")
else:
    print("  Aucune position ouverte (compte vierge)")

print("\n--- Test scoring engine ---")
from analysis.scorer import get_top_signals
signals = get_top_signals(10)
print(f"Top {len(signals)} signaux recents:\n")
for s in signals:
    bd = s.get("score_breakdown", {})
    print(f"  [{s['score']:5.1f}] {s['signal']:10s} | {s['politician']:25s} | "
          f"{s['ticker']:6s} | {s['trade_type']:4s} | {s['trade_date'][:10]}")
    print(f"         pol:{bd.get('politician_reliability',0):.1f} "
          f"inv:{bd.get('super_investor_alignment',0):.1f} "
          f"news:{bd.get('news_sentiment',0):.1f} "
          f"size:{bd.get('trade_size',0):.1f} "
          f"speed:{bd.get('disclosure_speed',0):.1f}")

disconnect()
print("\nDeconnexion IBKR. Test termine.")
