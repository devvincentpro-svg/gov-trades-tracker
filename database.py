import sqlite3
from config import DB_PATH


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id          TEXT PRIMARY KEY,
            politician  TEXT NOT NULL,
            chamber     TEXT NOT NULL,
            party       TEXT,
            state       TEXT,
            ticker      TEXT,
            asset_name  TEXT,
            trade_type  TEXT NOT NULL,
            trade_date  TEXT,
            disclosed   TEXT,
            amount_low  INTEGER,
            amount_high INTEGER,
            sources     TEXT,
            source_count INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS prices (
            ticker      TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            price       REAL,
            change_pct  REAL,
            volume      INTEGER,
            avg_volume  INTEGER,
            PRIMARY KEY (ticker, fetched_at)
        );

        CREATE TABLE IF NOT EXISTS fetch_log (
            source      TEXT NOT NULL,
            fetched_at  TEXT DEFAULT (datetime('now')),
            count       INTEGER,
            status      TEXT
        );

        CREATE TABLE IF NOT EXISTS news (
            id           TEXT PRIMARY KEY,
            ticker       TEXT,
            headline     TEXT,
            summary      TEXT,
            url          TEXT,
            source       TEXT,
            published_at TEXT,
            sentiment    REAL,
            sentiment_label TEXT,
            fetched_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_news_ticker ON news(ticker);
        CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);

        CREATE TABLE IF NOT EXISTS news_trades (
            news_id      TEXT,
            trade_id     TEXT,
            lead_days    REAL,
            PRIMARY KEY (news_id, trade_id)
        );
    """)
    conn.commit()
    conn.close()


def upsert_trade(trade: dict):
    conn = get_conn()
    existing = conn.execute(
        "SELECT sources, source_count FROM trades WHERE id = ?", (trade["id"],)
    ).fetchone()

    if existing:
        old_sources = existing[0] or ""
        new_source = trade.get("sources", "")
        merged = ",".join(sorted(set(filter(None, old_sources.split(",") + [new_source]))))
        conn.execute(
            "UPDATE trades SET sources = ?, source_count = ?, party = COALESCE(NULLIF(party,''), ?), state = COALESCE(NULLIF(state,''), ?) WHERE id = ?",
            (merged, len(merged.split(",")), trade.get("party"), trade.get("state"), trade["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO trades
               (id, politician, chamber, party, state, ticker, asset_name, trade_type,
                trade_date, disclosed, amount_low, amount_high, sources, source_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                trade["id"], trade["politician"], trade["chamber"],
                trade.get("party"), trade.get("state"), trade.get("ticker"),
                trade.get("asset_name"), trade["trade_type"],
                trade.get("trade_date"), trade.get("disclosed"),
                trade.get("amount_low"), trade.get("amount_high"),
                trade.get("sources", ""),
            ),
        )
    conn.commit()
    conn.close()


def upsert_price(ticker: str, price: float, change_pct: float, volume: int = 0, avg_volume: int = 0):
    from datetime import datetime
    conn = get_conn()
    # Migrate: add columns if they don't exist (safe no-op if already there)
    try:
        conn.execute("ALTER TABLE prices ADD COLUMN volume INTEGER")
        conn.execute("ALTER TABLE prices ADD COLUMN avg_volume INTEGER")
        conn.commit()
    except Exception:
        pass
    conn.execute(
        "INSERT OR REPLACE INTO prices (ticker, fetched_at, price, change_pct, volume, avg_volume) VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, datetime.utcnow().strftime("%Y-%m-%d %H:%M"), price, change_pct, volume, avg_volume),
    )
    conn.commit()
    conn.close()


def upsert_news(article: dict) -> bool:
    """Insert news article; returns True if new."""
    conn = get_conn()
    existing = conn.execute("SELECT 1 FROM news WHERE id = ?", (article["id"],)).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO news (id, ticker, headline, summary, url, source, published_at, sentiment, sentiment_label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                article["id"], article.get("ticker", ""), article.get("headline", ""),
                article.get("summary", ""), article.get("url", ""), article.get("source", ""),
                article.get("published_at", ""), article.get("sentiment", 0.0),
                article.get("sentiment_label", "neutral"),
            ),
        )
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def link_news_to_trades(news_id: str, trade_id: str, lead_days: float):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO news_trades (news_id, trade_id, lead_days) VALUES (?, ?, ?)",
        (news_id, trade_id, lead_days),
    )
    conn.commit()
    conn.close()


def log_fetch(source: str, count: int, status: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO fetch_log (source, count, status) VALUES (?, ?, ?)",
        (source, count, status),
    )
    conn.commit()
    conn.close()
