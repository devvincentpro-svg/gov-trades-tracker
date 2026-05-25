from database import init_db, get_conn
import pandas as pd

init_db()
conn = get_conn()
df = pd.read_sql_query("SELECT * FROM trades ORDER BY disclosed DESC", conn)
conn.close()

df["amount_mid"] = ((df["amount_low"].fillna(0) + df["amount_high"].fillna(0)) / 2).astype(int)

pol_df = df[(df["politician"] == "Ro Khanna") & (df["ticker"] != "")].copy()
port = (
    pol_df.groupby("ticker").agg(
        asset_name=("asset_name", "first"),
        buys=("trade_type", lambda x: (x == "buy").sum()),
        sells=("trade_type", lambda x: (x == "sell").sum()),
        buy_vol=("amount_mid", lambda x: x[pol_df.loc[x.index, "trade_type"] == "buy"].sum()),
        sell_vol=("amount_mid", lambda x: x[pol_df.loc[x.index, "trade_type"] == "sell"].sum()),
        last_trade=("trade_date", "max"),
    ).reset_index()
)
port["net_position"] = port["buy_vol"] - port["sell_vol"]
port_sorted = port.sort_values("buy_vol", ascending=False)

print(f"Ro Khanna portfolio: {len(port)} tickers")
print(port_sorted.head(15).to_string(index=False))
print(f"\nDB total: {len(df)} trades, {df['politician'].nunique()} politicians")
