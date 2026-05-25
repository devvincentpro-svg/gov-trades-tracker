import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from database import get_conn, init_db
from scheduler import start, run_all
import threading

st.set_page_config(
    page_title="Gov Trades Tracker",
    page_icon="📊",
    layout="wide",
)

# --- Init DB + scheduler (once per process) ---
init_db()

if "scheduler_started" not in st.session_state:
    run_all()  # first load: fetch immediately
    start()
    st.session_state["scheduler_started"] = True


# --- Data loaders ---
@st.cache_data(ttl=60)
def load_trades() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM trades ORDER BY disclosed DESC, trade_date DESC",
        conn,
    )
    conn.close()
    if df.empty:
        return df
    df["amount_mid"] = ((df["amount_low"].fillna(0) + df["amount_high"].fillna(0)) / 2).astype(int)
    df["source_count"] = df["source_count"].fillna(1).astype(int)
    df["confidence"] = df["source_count"].map({1: "Low", 2: "Medium", 3: "High"}).fillna("High")
    return df


@st.cache_data(ttl=60)
def load_prices() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        """SELECT p.* FROM prices p
           INNER JOIN (
               SELECT ticker, MAX(fetched_at) as latest FROM prices GROUP BY ticker
           ) l ON p.ticker = l.ticker AND p.fetched_at = l.latest""",
        conn,
    )
    conn.close()
    return df


@st.cache_data(ttl=300)
def load_log() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM fetch_log ORDER BY fetched_at DESC LIMIT 20",
        conn,
    )
    conn.close()
    return df


# --- Layout ---
st.title("📊 Gov Trades Tracker")
st.caption("Données croisées : House Stock Watcher · Senate Stock Watcher · Capitol Trades · Finnhub · OpenSecrets · Prix Yahoo Finance")

df = load_trades()
prices = load_prices()

if df.empty:
    st.warning("Chargement des données en cours... Actualisez dans quelques secondes.")
    st.stop()

# --- KPIs ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Trades total", f"{len(df):,}")
col2.metric("Élus uniques", df["politician"].nunique())
col3.metric("Tickers uniques", df["ticker"].replace("", pd.NA).dropna().nunique())
multi = df[df["source_count"] > 1]
col4.metric("Confirmés par 2+ sources", len(multi), help="Même trade trouvé dans plusieurs bases")

st.divider()

# --- Filters ---
with st.sidebar:
    st.header("Filtres")
    chamber = st.multiselect("Chambre", ["house", "senate"], default=["house", "senate"])
    trade_type = st.multiselect("Type", ["buy", "sell", "exchange"], default=["buy", "sell"])
    min_sources = st.slider("Sources minimum", 1, 3, 1)
    top_n = st.slider("Top N politiciens", 5, 30, 15)

filtered = df[
    df["chamber"].isin(chamber) &
    df["trade_type"].isin(trade_type) &
    (df["source_count"] >= min_sources)
]

# --- Fil des derniers trades ---
st.subheader("🕐 Derniers trades déclarés")

recent = filtered.head(50).copy()
recent["Montant estimé"] = recent["amount_mid"].apply(
    lambda x: f"${x:,}" if x > 0 else "N/A"
)
recent["🔵/🔴"] = recent["trade_type"].map({"buy": "🟢 Achat", "sell": "🔴 Vente", "exchange": "🔄 Échange"})
recent["Sources"] = recent["source_count"].apply(lambda x: "⭐" * min(x, 3))

st.dataframe(
    recent[["politician", "chamber", "ticker", "asset_name", "🔵/🔴", "trade_date", "disclosed", "Montant estimé", "Sources"]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "politician": "Élu",
        "chamber": "Chambre",
        "ticker": "Ticker",
        "asset_name": "Actif",
        "trade_date": "Date trade",
        "disclosed": "Date déclaration",
    },
)

st.divider()

# --- Charts ---
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🏆 Top élus par volume")
    top = (
        filtered.groupby("politician")["amount_mid"]
        .sum()
        .nlargest(top_n)
        .reset_index()
    )
    top.columns = ["Élu", "Montant total estimé"]
    fig = px.bar(top, x="Montant total estimé", y="Élu", orientation="h",
                 color="Montant total estimé", color_continuous_scale="Blues")
    fig.update_layout(showlegend=False, yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.subheader("📈 Achats vs Ventes")
    type_counts = filtered["trade_type"].value_counts().reset_index()
    type_counts.columns = ["Type", "Nombre"]
    type_counts["Type"] = type_counts["Type"].map(
        {"buy": "Achat", "sell": "Vente", "exchange": "Échange"}
    ).fillna(type_counts["Type"])
    fig2 = px.pie(type_counts, names="Type", values="Nombre",
                  color="Type", color_discrete_map={"Achat": "#2ecc71", "Vente": "#e74c3c", "Échange": "#3498db"})
    st.plotly_chart(fig2, use_container_width=True)

# --- Tickers les plus tradés ---
st.subheader("🔥 Tickers les plus tradés")
ticker_counts = (
    filtered[filtered["ticker"] != ""]
    .groupby(["ticker", "trade_type"])
    .size()
    .reset_index(name="count")
)
top_tickers = ticker_counts.groupby("ticker")["count"].sum().nlargest(20).index
ticker_counts = ticker_counts[ticker_counts["ticker"].isin(top_tickers)]

fig3 = px.bar(
    ticker_counts, x="ticker", y="count", color="trade_type",
    color_discrete_map={"buy": "#2ecc71", "sell": "#e74c3c", "exchange": "#3498db"},
    barmode="stack",
)
fig3.update_layout(xaxis_title="Ticker", yaxis_title="Nombre de trades", legend_title="Type")
st.plotly_chart(fig3, use_container_width=True)

# --- Prix en temps réel ---
if not prices.empty:
    st.subheader("💹 Prix en temps réel (15 min delay via Yahoo Finance)")
    prices_display = prices.merge(
        filtered[["ticker"]].drop_duplicates(), on="ticker"
    ).sort_values("change_pct", ascending=False)

    prices_display["Variation"] = prices_display["change_pct"].apply(
        lambda x: f"{'▲' if x > 0 else '▼'} {abs(x):.2f}%"
    )
    st.dataframe(
        prices_display[["ticker", "price", "Variation", "fetched_at"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": "Ticker",
            "price": st.column_config.NumberColumn("Prix ($)", format="$%.2f"),
            "fetched_at": "Mis à jour",
        },
    )

# --- Évolution temporelle ---
st.subheader("📅 Volume de trades dans le temps")
if "trade_date" in filtered.columns:
    timeline = filtered[filtered["trade_date"] != ""].copy()
    timeline["trade_date"] = pd.to_datetime(timeline["trade_date"], errors="coerce")
    timeline = timeline.dropna(subset=["trade_date"])
    timeline = timeline.groupby([timeline["trade_date"].dt.to_period("M"), "trade_type"]).size().reset_index(name="count")
    timeline["trade_date"] = timeline["trade_date"].astype(str)
    fig4 = px.line(timeline, x="trade_date", y="count", color="trade_type",
                   color_discrete_map={"buy": "#2ecc71", "sell": "#e74c3c"},
                   labels={"trade_date": "Mois", "count": "Nombre de trades", "trade_type": "Type"})
    st.plotly_chart(fig4, use_container_width=True)

# --- Sources breakdown ---
st.subheader("🗂 Couverture par source")
source_stats = []
for src in ["house_watcher", "senate_watcher", "capitol_trades", "finnhub", "opensecrets"]:
    mask = df["sources"].str.contains(src, na=False)
    source_stats.append({
        "Source": src.replace("_", " ").title(),
        "Trades couverts": mask.sum(),
        "Élus uniques": df[mask]["politician"].nunique(),
    })
src_df = pd.DataFrame(source_stats)
st.dataframe(src_df, use_container_width=True, hide_index=True)

# --- PFD Assets (OpenSecrets) ---
try:
    conn = get_conn()
    pfd = pd.read_sql_query(
        "SELECT politician, asset_name, asset_type, value_low, value_high FROM pfd_assets ORDER BY value_high DESC LIMIT 100",
        conn,
    )
    conn.close()
    if not pfd.empty:
        st.subheader("💼 Holdings déclarés (OpenSecrets PFD)")
        pfd["Valeur estimée"] = ((pfd["value_low"] + pfd["value_high"]) / 2).apply(lambda x: f"${x:,.0f}")
        st.dataframe(pfd[["politician", "asset_name", "asset_type", "Valeur estimée"]],
                     use_container_width=True, hide_index=True)
except Exception:
    pass

# --- Logs ---
with st.expander("🔧 Logs de synchronisation"):
    log_df = load_log()
    st.dataframe(log_df, use_container_width=True, hide_index=True)

st.caption(f"Actualisation auto toutes les 15 min · Dernière mise à jour DB : {df['created_at'].max()}")
