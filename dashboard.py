import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from database import get_conn, init_db
from scheduler import start, run_all
from analysis.cross_reference import get_shared_tickers, get_top_aligned_trades, get_alignment
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
def load_ticker_info() -> pd.DataFrame:
    conn = get_conn()
    try:
        df = pd.read_sql_query("SELECT * FROM ticker_info", conn)
    except Exception:
        df = pd.DataFrame()
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
st.caption("Sources : Capitol Trades · Congress.gov API · Finnhub · Yahoo Finance · SEC EDGAR 13F · Dataroma (super investisseurs)")

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

# --- Parti républicain vs démocrate ---
if "party" in filtered.columns:
    party_data = filtered[filtered["party"].isin(["Republican", "Democrat", "R", "D"])]
    if not party_data.empty:
        st.subheader("🔴🔵 Trades par parti politique")
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            party_type = party_data.groupby(["party", "trade_type"]).size().reset_index(name="count")
            fig_party = px.bar(party_type, x="party", y="count", color="trade_type",
                               color_discrete_map={"buy": "#2ecc71", "sell": "#e74c3c"},
                               barmode="group",
                               labels={"party": "Parti", "count": "Trades", "trade_type": "Type"})
            st.plotly_chart(fig_party, use_container_width=True)
        with col_p2:
            party_vol = party_data.groupby("party")["amount_mid"].sum().reset_index()
            party_vol.columns = ["Parti", "Volume estimé ($)"]
            fig_pvol = px.bar(party_vol, x="Parti", y="Volume estimé ($)",
                              color="Parti",
                              color_discrete_map={"Republican": "#e74c3c", "Democrat": "#3498db",
                                                  "R": "#e74c3c", "D": "#3498db"})
            st.plotly_chart(fig_pvol, use_container_width=True)

# --- Secteurs les plus tradés (via Finnhub) ---
ticker_info = load_ticker_info()
if not ticker_info.empty:
    st.subheader("🏭 Secteurs les plus tradés (enrichissement Finnhub)")
    merged_sectors = filtered.merge(ticker_info[["ticker", "sector"]], on="ticker", how="left")
    sector_counts = (
        merged_sectors[merged_sectors["sector"].notna() & (merged_sectors["sector"] != "")]
        .groupby(["sector", "trade_type"])
        .size()
        .reset_index(name="count")
    )
    if not sector_counts.empty:
        fig_s = px.bar(
            sector_counts, x="sector", y="count", color="trade_type",
            color_discrete_map={"buy": "#2ecc71", "sell": "#e74c3c", "exchange": "#3498db"},
            barmode="stack",
            labels={"sector": "Secteur", "count": "Trades", "trade_type": "Type"},
        )
        fig_s.update_layout(xaxis_tickangle=-35)
        st.plotly_chart(fig_s, use_container_width=True)

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

# ═══════════════════════════════════════════════════════════
# SUPER INVESTISSEURS — CROISEMENT
# ═══════════════════════════════════════════════════════════
st.divider()
st.header("🐋 Croisement Super Investisseurs")

@st.cache_data(ttl=300)
def load_shared():
    return get_shared_tickers()

@st.cache_data(ttl=300)
def load_top_aligned():
    return get_top_aligned_trades(20)

shared = load_shared()
top_aligned = load_top_aligned()

if shared:
    col_s1, col_s2 = st.columns(2)

    with col_s1:
        st.subheader("🔗 Tickers tradés par élus ET détenus par super investisseurs")
        sh_df = pd.DataFrame(shared)
        sh_df.columns = ["Ticker", "Élus", "Super Investisseurs", "Volume politique ($)"]
        fig_sh = px.scatter(
            sh_df, x="Super Investisseurs", y="Élus",
            size="Volume politique ($)", text="Ticker",
            color="Super Investisseurs", color_continuous_scale="Blues",
            labels={"Super Investisseurs": "Nb super investisseurs", "Élus": "Nb élus"},
            title="Convergence smart money / élus"
        )
        fig_sh.update_traces(textposition="top center")
        st.plotly_chart(fig_sh, use_container_width=True)

    with col_s2:
        st.subheader("📊 Top tickers convergents")
        st.dataframe(
            sh_df.head(20),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Volume politique ($)": st.column_config.NumberColumn(format="$%d"),
            }
        )

if top_aligned:
    st.subheader("⭐ Trades politiques les plus alignés avec le smart money")
    al_df = pd.DataFrame(top_aligned)
    al_df["trade_type"] = al_df["trade_type"].map({"buy": "🟢 Achat", "sell": "🔴 Vente"}).fillna(al_df["trade_type"])
    al_df["alignment_score"] = al_df["alignment_score"].apply(lambda x: f"{x:.1f}%")
    st.dataframe(
        al_df[["ticker", "politician", "trade_type", "trade_date", "super_investors_count", "alignment_score", "top_investor"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": "Ticker",
            "politician": "Élu",
            "trade_type": "Type",
            "trade_date": "Date",
            "super_investors_count": "# Super Inv.",
            "alignment_score": "Score alignement",
            "top_investor": "Principal super investisseur",
        }
    )

    # Detail: click on ticker → show who holds it
    selected = st.selectbox("Détail super investisseurs pour :", [""] + [t["ticker"] for t in top_aligned])
    if selected:
        investors = get_alignment(selected)
        if investors:
            inv_df = pd.DataFrame(investors)
            inv_df["value_usd"] = inv_df["value_usd"].apply(lambda x: f"${x:,.0f}")
            inv_df["shares"] = inv_df["shares"].apply(lambda x: f"{x:,}")
            st.dataframe(inv_df, use_container_width=True, hide_index=True)

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
for src in ["congress_api", "finnhub_enrich"]:
    source_stats.append({
        "Source": src.replace("_", " ").title() + " (enrichissement)",
        "Trades couverts": "—",
        "Élus uniques": "—",
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
    pass
except Exception:
    pass

# --- Logs ---
with st.expander("🔧 Logs de synchronisation"):
    log_df = load_log()
    st.dataframe(log_df, use_container_width=True, hide_index=True)

st.caption(f"Actualisation auto toutes les 15 min · Dernière mise à jour DB : {df['created_at'].max()}")
