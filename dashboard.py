import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from database import get_conn, init_db
from scheduler import start, run_all
from analysis.cross_reference import get_shared_tickers, get_top_aligned_trades, get_alignment
from analysis.news_correlation import (
    get_advance_trades, get_politician_timing_stats,
    get_ticker_sentiment_timeline, get_news_for_ticker, get_sentiment_vs_trades
)
from analysis.scorer import get_top_signals
import threading

# IBKR — connexion optionnelle, ne bloque pas si TWS est fermé
try:
    from broker.ibkr_client import connect as ibkr_connect, account_summary, get_positions, is_connected
    from broker.ibkr_orders import get_paper_orders, place_order
    _IBKR_AVAILABLE = True
except Exception:
    _IBKR_AVAILABLE = False

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
    # Migrate columns if they don't exist
    try:
        conn.execute("ALTER TABLE prices ADD COLUMN volume INTEGER")
        conn.execute("ALTER TABLE prices ADD COLUMN avg_volume INTEGER")
        conn.commit()
    except Exception:
        pass
    df = pd.read_sql_query(
        """SELECT p.ticker, p.price, p.change_pct,
                  COALESCE(p.volume, 0) as volume,
                  COALESCE(p.avg_volume, 0) as avg_volume,
                  p.fetched_at
           FROM prices p
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

# --- Most active politicians quick overview ---
st.subheader("🏅 Élus les plus actifs")
overview = (
    df.groupby(["politician", "party", "chamber", "state"])
    .agg(
        trades=("id", "count"),
        volume=("amount_mid", "sum"),
        last_trade=("trade_date", "max"),
        tickers=("ticker", lambda x: x[x != ""].nunique()),
    )
    .reset_index()
    .sort_values("trades", ascending=False)
    .head(30)
)
overview["party_label"] = overview["party"].map(
    {"D": "Dem.", "Democrat": "Dem.", "R": "Rép.", "Republican": "Rép.", "I": "Ind."}
).fillna(overview["party"])
st.dataframe(
    overview[["politician", "party_label", "chamber", "state", "trades", "volume", "tickers", "last_trade"]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "politician": "Élu",
        "party_label": "Parti",
        "chamber": "Chambre",
        "state": "État",
        "trades": st.column_config.NumberColumn("# Trades", format="%d"),
        "volume": st.column_config.NumberColumn("Volume estimé ($)", format="$%,.0f"),
        "tickers": st.column_config.NumberColumn("Tickers distincts", format="%d"),
        "last_trade": "Dernier trade",
    },
)

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
# PORTEFEUILLE PAR ÉLU
# ═══════════════════════════════════════════════════════════
st.divider()
st.header("🗂 Portefeuille par élu")

politicians_with_trades = sorted(df[df["ticker"] != ""]["politician"].unique())
selected_pol = st.selectbox("Choisir un élu", [""] + list(politicians_with_trades), key="pol_select")

if selected_pol:
    pol_df = df[(df["politician"] == selected_pol) & (df["ticker"] != "")].copy()

    # Aggregate per ticker: buys vs sells, amounts, last trade
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
    port["statut"] = port.apply(
        lambda r: "Actif (achat net)" if r["net_position"] > 0 else ("Sorti (vente net)" if r["net_position"] < 0 else "Neutre"),
        axis=1
    )

    # Join latest prices + volume
    latest_prices = load_prices()
    if not latest_prices.empty:
        port = port.merge(
            latest_prices[["ticker", "price", "change_pct", "volume", "avg_volume"]].rename(
                columns={"change_pct": "variation_%"}
            ),
            on="ticker", how="left"
        )
        port["market_cap_traded"] = (port["price"].fillna(0) * port["buy_vol"].fillna(0) / port["price"].fillna(1)).round(0)
    else:
        port[["price", "variation_%", "volume", "avg_volume"]] = None

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Positions distinctes", port["ticker"].nunique())
    c2.metric("Total achat estimé", f"${port['buy_vol'].sum():,.0f}")
    c3.metric("Total vente estimé", f"${port['sell_vol'].sum():,.0f}")
    active_count = (port["net_position"] > 0).sum()
    c4.metric("Positions actives (achat net)", active_count)

    # Portfolio table
    port_display = port[[
        "ticker", "asset_name", "buys", "sells", "buy_vol", "sell_vol",
        "net_position", "statut", "price", "variation_%", "volume", "avg_volume", "last_trade"
    ]].sort_values("buy_vol", ascending=False)

    st.dataframe(
        port_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": "Ticker",
            "asset_name": "Actif",
            "buys": st.column_config.NumberColumn("Achats", format="%d"),
            "sells": st.column_config.NumberColumn("Ventes", format="%d"),
            "buy_vol": st.column_config.NumberColumn("Vol. achat ($)", format="$%,.0f"),
            "sell_vol": st.column_config.NumberColumn("Vol. vente ($)", format="$%,.0f"),
            "net_position": st.column_config.NumberColumn("Position nette ($)", format="$%,.0f"),
            "statut": "Statut",
            "price": st.column_config.NumberColumn("Prix actuel ($)", format="$%.2f"),
            "variation_%": st.column_config.NumberColumn("Variation j.", format="%.2f%%"),
            "volume": st.column_config.NumberColumn("Volume jour", format="%,d"),
            "avg_volume": st.column_config.NumberColumn("Vol. moyen 3M", format="%,d"),
            "last_trade": "Dernier trade",
        }
    )

    # Bubble chart: positions active
    active_port = port[port["net_position"] > 0].dropna(subset=["price"])
    if not active_port.empty:
        fig_port = px.scatter(
            active_port,
            x="variation_%", y="price",
            size="buy_vol",
            text="ticker",
            color="net_position",
            color_continuous_scale="Greens",
            labels={"variation_%": "Variation jour (%)", "price": "Prix ($)", "buy_vol": "Vol. achat ($)"},
            title=f"Positions actives de {selected_pol}",
        )
        fig_port.update_traces(textposition="top center")
        st.plotly_chart(fig_port, use_container_width=True)

    # Trade history for this politician
    with st.expander(f"Historique complet ({len(pol_df)} trades)"):
        hist = pol_df[["trade_date", "ticker", "asset_name", "trade_type", "amount_mid", "disclosed"]].copy()
        hist["trade_type"] = hist["trade_type"].map({"buy": "🟢 Achat", "sell": "🔴 Vente", "exchange": "🔄"}).fillna(hist["trade_type"])
        hist["amount_mid"] = hist["amount_mid"].apply(lambda x: f"${x:,}" if x > 0 else "N/A")
        st.dataframe(hist.sort_values("trade_date", ascending=False), use_container_width=True, hide_index=True)

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

# ═══════════════════════════════════════════════════════════
# NEWS & RÉSEAUX SOCIAUX — ANALYSE DE TIMING
# ═══════════════════════════════════════════════════════════
st.divider()
st.header("📰 News, Réseaux Sociaux & Timing des trades")
st.caption("Sources : Finnhub · Yahoo Finance · Google News · GDELT · Reddit  |  Sentiment : VADER  |  Twitter : configuration requise")

@st.cache_data(ttl=120)
def load_timing_stats():
    return get_politician_timing_stats()

@st.cache_data(ttl=120)
def load_advance_trades(min_lead):
    return get_advance_trades(min_lead_days=min_lead, limit=60)

timing_stats = load_timing_stats()

if timing_stats:
    st.subheader("⏱ Élus en avance sur le cycle des nouvelles")
    st.caption("avg_lead_days > 0 : l'élu a tradé en moyenne X jours **avant** que la presse en parle")

    ts_df = pd.DataFrame(timing_stats)
    ts_df["pct_ahead"] = (ts_df["trades_ahead"] / ts_df["trades_with_news"].replace(0, 1) * 100).round(1)
    ts_df["avg_lead_days"] = ts_df["avg_lead_days"].round(1)
    ts_df["avg_news_sentiment"] = ts_df["avg_news_sentiment"].round(3)
    ts_df["sentiment_icon"] = ts_df["avg_news_sentiment"].apply(
        lambda x: "📈" if x > 0.05 else ("📉" if x < -0.05 else "—")
    )
    ts_df["party_label"] = ts_df["party"].map(
        {"D": "Dem.", "Democrat": "Dem.", "R": "Rép.", "Republican": "Rép."}
    ).fillna(ts_df["party"])

    col_t1, col_t2 = st.columns([3, 2])
    with col_t1:
        fig_timing = px.bar(
            ts_df.head(20), x="avg_lead_days", y="politician",
            orientation="h", color="avg_lead_days",
            color_continuous_scale="RdYlGn",
            labels={"avg_lead_days": "Jours d'avance moy.", "politician": "Élu"},
            title="Avance moyenne sur les nouvelles (jours)",
        )
        fig_timing.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
        st.plotly_chart(fig_timing, use_container_width=True)

    with col_t2:
        st.dataframe(
            ts_df[["politician", "party_label", "avg_lead_days", "pct_ahead",
                   "trades_ahead", "trades_with_news", "sentiment_icon"]].head(20),
            use_container_width=True,
            hide_index=True,
            column_config={
                "politician": "Élu",
                "party_label": "Parti",
                "avg_lead_days": st.column_config.NumberColumn("Avance moy. (j)", format="%.1f"),
                "pct_ahead": st.column_config.NumberColumn("% trades en avance", format="%.1f%%"),
                "trades_ahead": st.column_config.NumberColumn("Trades en avance", format="%d"),
                "trades_with_news": st.column_config.NumberColumn("Trades liés à news", format="%d"),
                "sentiment_icon": "Sentiment news",
            },
        )
else:
    st.info("Données de corrélation news en cours de collecte... La première exécution peut prendre quelques minutes.")

st.divider()

# ── Trades anticipatoires ──
st.subheader("🚨 Trades passés AVANT une news significative")
min_lead = st.slider("Délai minimum (jours avant la news)", 1, 30, 5, key="lead_slider")
advance = load_advance_trades(min_lead)

if advance:
    adv_df = pd.DataFrame(advance)
    adv_df["trade_type"] = adv_df["trade_type"].map({"buy": "🟢 Achat", "sell": "🔴 Vente"}).fillna(adv_df["trade_type"])
    adv_df["sentiment_icon"] = adv_df["sentiment"].apply(
        lambda x: f"📈 +{x:.2f}" if x > 0.05 else (f"📉 {x:.2f}" if x < -0.05 else f"— {x:.2f}")
    )
    adv_df["amount_fmt"] = adv_df["amount"].apply(lambda x: f"${x:,.0f}" if x > 0 else "N/A")

    st.dataframe(
        adv_df[["politician", "party", "ticker", "trade_type", "trade_date",
                "lead_days", "amount_fmt", "headline", "published_at", "sentiment_icon", "source"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "politician": "Élu",
            "party": "Parti",
            "ticker": "Ticker",
            "trade_type": "Type",
            "trade_date": "Date trade",
            "lead_days": st.column_config.NumberColumn("Jours avant news", format="%.1f"),
            "amount_fmt": "Montant",
            "headline": "Titre de la news",
            "published_at": "Date news",
            "sentiment_icon": "Sentiment",
            "source": "Source",
        },
    )

    # Scatter: lead_days vs sentiment, colored by politician
    fig_lead = px.scatter(
        adv_df, x="lead_days", y="sentiment", color="politician",
        size="amount", hover_data=["ticker", "headline", "trade_type"],
        labels={"lead_days": "Jours avant la news", "sentiment": "Sentiment de la news"},
        title="Avance sur news vs sentiment : chaque point = 1 trade",
    )
    fig_lead.add_hline(y=0, line_dash="dash", line_color="gray")
    fig_lead.add_vline(x=0, line_dash="dash", line_color="gray")
    fig_lead.update_layout(
        annotations=[
            dict(x=15, y=0.5, text="Achat avant bonne news", showarrow=False, font=dict(color="green")),
            dict(x=15, y=-0.5, text="Vente avant mauvaise news", showarrow=False, font=dict(color="red")),
        ]
    )
    st.plotly_chart(fig_lead, use_container_width=True)
else:
    st.info("Aucun trade anticipatoire trouvé pour ce seuil. Les données news se collectent en arrière-plan.")

st.divider()

# ── Sentiment & timeline par ticker ──
st.subheader("📊 Sentiment & trades par ticker")
ticker_list = sorted(df[df["ticker"] != ""]["ticker"].unique())
sel_ticker = st.selectbox("Choisir un ticker", [""] + list(ticker_list), key="news_ticker")

if sel_ticker:
    col_n1, col_n2 = st.columns([2, 1])

    with col_n1:
        sentiment_df = get_ticker_sentiment_timeline(sel_ticker)
        trades_ticker = df[(df["ticker"] == sel_ticker) & (df["trade_date"] != "")].copy()
        trades_ticker["trade_date"] = pd.to_datetime(trades_ticker["trade_date"], errors="coerce")
        trades_ticker = trades_ticker.dropna(subset=["trade_date"])

        if not sentiment_df.empty or not trades_ticker.empty:
            fig_tl = go.Figure()

            if not sentiment_df.empty:
                fig_tl.add_trace(go.Scatter(
                    x=sentiment_df["published_at"], y=sentiment_df["sentiment"],
                    mode="markers", name="Sentiment news",
                    marker=dict(
                        color=sentiment_df["sentiment"],
                        colorscale="RdYlGn", size=8, cmin=-1, cmax=1,
                        showscale=True, colorbar=dict(title="Sentiment"),
                    ),
                    hovertext=sentiment_df["headline"],
                    hoverinfo="text+x+y",
                ))

            for _, trade in trades_ticker.iterrows():
                color = "#2ecc71" if trade["trade_type"] == "buy" else "#e74c3c"
                fig_tl.add_vline(
                    x=trade["trade_date"].timestamp() * 1000,
                    line_dash="dot", line_color=color, opacity=0.6,
                    annotation_text=f"{trade['politician'][:10]} {trade['trade_type']}",
                    annotation_font_size=9,
                )

            fig_tl.update_layout(
                title=f"Timeline sentiment news + trades — {sel_ticker}",
                xaxis_title="Date", yaxis_title="Score sentiment",
                hovermode="closest",
            )
            st.plotly_chart(fig_tl, use_container_width=True)
        else:
            st.info(f"Pas encore de news pour {sel_ticker}. Lancez une synchronisation.")

    with col_n2:
        st.write(f"**Dernières news — {sel_ticker}**")
        news_list = get_news_for_ticker(sel_ticker, 15)
        if news_list:
            for art in news_list:
                icon = "📈" if art["sentiment_label"] == "positive" else ("📉" if art["sentiment_label"] == "negative" else "—")
                src_short = art["source"].split(":")[0].replace("_", " ")
                with st.container():
                    if art["url"]:
                        st.markdown(f"{icon} [{art['headline'][:80]}...]({art['url']})")
                    else:
                        st.write(f"{icon} {art['headline'][:80]}...")
                    st.caption(f"{art['published_at'][:10]} · {src_short} · score: {art['sentiment']:.2f}")
        else:
            st.info("Aucune news en base pour ce ticker.")

st.divider()

# ── Note Twitter / Facebook ──
with st.expander("📢 Configuration Twitter / Facebook"):
    st.markdown("""
**Twitter/X** (optionnel — données sociales les plus riches)
1. Créer un compte développeur sur [developer.twitter.com](https://developer.twitter.com)
2. Créer une app, récupérer le **Bearer Token** (accès gratuit : 500K tweets/mois)
3. Ajouter dans `.env` :
   ```
   TWITTER_BEARER_TOKEN=votre_token_ici
   ```
4. Le module `ingestion/news_fetcher.py` utilisera automatiquement Twitter.

**Facebook** — API Graph très restrictive (approbation requise, pages publiques seulement).
En pratique, le signal Reddit + Google News couvre 95% du bruit social utile.
    """)

# ═══════════════════════════════════════════════════════════
# IBKR PAPER TRADING — SIGNAUX & PORTEFEUILLE SIMULÉ
# ═══════════════════════════════════════════════════════════
st.divider()
st.header("🏦 IBKR Paper Trading — Signaux & Simulation")

# ── Scoring engine ──
@st.cache_data(ttl=60)
def load_signals():
    return get_top_signals(20)

signals = load_signals()

if signals:
    st.subheader("🎯 Top signaux politiques scorés")
    st.caption("Score 0-100 : fiabilité élu (30) + super investisseurs (25) + news sentiment (20) + taille trade (15) + vitesse déclaration (10)")

    sig_df = pd.DataFrame(signals)
    sig_df["signal_icon"] = sig_df["signal"].map({
        "STRONG BUY": "🟢🟢 FORT ACHAT",
        "BUY":        "🟢 ACHAT",
        "WATCH":      "🟡 SURVEILLER",
        "WEAK":       "🟠 FAIBLE",
        "SKIP":       "⚫ IGNORER",
    }).fillna(sig_df["signal"])
    sig_df["amount_mid"] = ((sig_df["amount_low"].fillna(0) + sig_df["amount_high"].fillna(0)) / 2).astype(int)
    sig_df["montant"] = sig_df["amount_mid"].apply(lambda x: f"${x:,}" if x > 0 else "N/A")
    sig_df["breakdown"] = sig_df["score_breakdown"].apply(
        lambda b: f"pol:{b.get('politician_reliability',0):.0f} "
                  f"inv:{b.get('super_investor_alignment',0):.0f} "
                  f"news:{b.get('news_sentiment',0):.0f} "
                  f"size:{b.get('trade_size',0):.0f} "
                  f"speed:{b.get('disclosure_speed',0):.0f}"
    )

    # Score bar chart
    fig_score = px.bar(
        sig_df.head(15), x="score", y="politician",
        orientation="h", color="score",
        color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
        color_continuous_midpoint=60,
        text="ticker",
        labels={"score": "Score (0-100)", "politician": "Élu"},
        title="Signaux par élu (60 derniers jours)",
    )
    fig_score.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
    fig_score.update_traces(textposition="inside")
    st.plotly_chart(fig_score, use_container_width=True)

    st.dataframe(
        sig_df[["score", "signal_icon", "politician", "ticker", "trade_type",
                "trade_date", "montant", "breakdown"]].head(20),
        use_container_width=True, hide_index=True,
        column_config={
            "score": st.column_config.NumberColumn("Score", format="%.1f"),
            "signal_icon": "Signal",
            "politician": "Élu",
            "ticker": "Ticker",
            "trade_type": "Type",
            "trade_date": "Date trade",
            "montant": "Montant",
            "breakdown": "Détail score",
        }
    )
else:
    st.info("Aucun signal calculé — les trades récents apparaîtront ici.")

st.divider()

# ── IBKR connexion live ──
st.subheader("📡 Connexion IBKR TWS (Paper)")

if _IBKR_AVAILABLE:
    col_ibkr1, col_ibkr2 = st.columns([1, 3])
    with col_ibkr1:
        if st.button("🔌 Connecter TWS", key="ibkr_connect"):
            with st.spinner("Connexion à TWS port 7497..."):
                ok = ibkr_connect()
            if ok:
                st.success("Connecté !")
            else:
                st.error("Échec — TWS ouvert et API activée ?")

    connected = is_connected()
    st.caption(f"État : {'🟢 Connecté' if connected else '🔴 Déconnecté (lancez TWS + cliquez Connecter)'}")

    if connected:
        # Account summary
        summary = account_summary()
        if summary:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Liquidation nette", f"${summary.get('NetLiquidation', 0):,.0f}")
            c2.metric("Cash disponible", f"${summary.get('TotalCashValue', 0):,.0f}")
            c3.metric("Fonds disponibles", f"${summary.get('AvailableFunds', 0):,.0f}")
            pnl = summary.get('UnrealizedPnL', 0)
            c4.metric("P&L non réalisé", f"${pnl:,.0f}", delta=f"{pnl:+,.0f}")

        # Open positions
        positions = get_positions()
        if positions:
            st.write("**Positions ouvertes (paper)**")
            pos_df = pd.DataFrame(positions)
            st.dataframe(pos_df, use_container_width=True, hide_index=True,
                        column_config={
                            "symbol": "Ticker",
                            "qty": st.column_config.NumberColumn("Quantité", format="%d"),
                            "avg_cost": st.column_config.NumberColumn("Coût moy.", format="$%.2f"),
                            "market_value": st.column_config.NumberColumn("Valeur marché", format="$%.2f"),
                        })

        # Manual signal execution
        st.write("**Exécuter un signal manuellement**")
        if signals:
            top_sig = signals[0]
            col_ex1, col_ex2, col_ex3 = st.columns(3)
            with col_ex1:
                exec_ticker = st.selectbox("Ticker", [s["ticker"] for s in signals[:10]], key="exec_ticker")
            with col_ex2:
                exec_action = st.selectbox("Action", ["BUY", "SELL"], key="exec_action")
            with col_ex3:
                exec_budget = st.number_input("Budget ($)", value=1000, min_value=100, max_value=10000, step=100, key="exec_budget")

            sel_sig = next((s for s in signals if s["ticker"] == exec_ticker), signals[0])
            st.caption(f"Signal sélectionné : score {sel_sig['score']:.1f} — {sel_sig['signal']} — {sel_sig['politician']}")

            if st.button(f"📤 Passer ordre PAPER {exec_action} {exec_ticker}", key="place_order"):
                with st.spinner("Passage de l'ordre..."):
                    result = place_order(
                        exec_ticker, exec_action,
                        score=sel_sig["score"],
                        politician=sel_sig["politician"],
                        trade_ref=sel_sig["id"],
                        budget_usd=exec_budget,
                    )
                if result.get("status") in ("Filled", "Submitted", "PreSubmitted"):
                    st.success(f"Ordre {exec_action} {result.get('qty')} {exec_ticker} @ ${result.get('fill_price')} — Total: ${result.get('total_usd'):,.0f}")
                else:
                    st.error(f"Erreur: {result.get('reason', result.get('status'))}")

# ── Historique des ordres paper ──
st.write("**Historique ordres paper**")
try:
    orders = get_paper_orders(30)
    if orders:
        ord_df = pd.DataFrame(orders)
        ord_df["pnl_fmt"] = ord_df["pnl"].apply(lambda x: f"${x:+,.0f}" if x else "—")
        st.dataframe(
            ord_df[["placed_at", "ticker", "action", "qty", "fill_price",
                    "status", "signal_score", "politician", "pnl_fmt"]],
            use_container_width=True, hide_index=True,
            column_config={
                "placed_at": "Date",
                "ticker": "Ticker",
                "action": "Action",
                "qty": st.column_config.NumberColumn("Qté", format="%d"),
                "fill_price": st.column_config.NumberColumn("Prix exec.", format="$%.2f"),
                "status": "Statut",
                "signal_score": st.column_config.NumberColumn("Score", format="%.1f"),
                "politician": "Élu suivi",
                "pnl_fmt": "P&L",
            }
        )
    else:
        st.info("Aucun ordre passé encore — utilisez le formulaire ci-dessus.")
except Exception:
    st.info("Aucun ordre passé encore.")

# --- Logs ---
with st.expander("🔧 Logs de synchronisation"):
    log_df = load_log()
    st.dataframe(log_df, use_container_width=True, hide_index=True)

st.caption(f"Actualisation auto toutes les 15 min · Dernière mise à jour DB : {df['created_at'].max()}")
