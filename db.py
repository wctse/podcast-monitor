import os
import sqlite3

_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "episodes.db")


def _connect(db_path: str = _DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = _DB_PATH):
    conn = _connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            podcast_slug TEXT NOT NULL,
            episode_url TEXT NOT NULL,
            episode_title TEXT,
            transcript_chars INTEGER DEFAULT 0,
            processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(podcast_slug, episode_url)
        );
        CREATE INDEX IF NOT EXISTS idx_episodes_slug ON episodes(podcast_slug);
    """)
    conn.commit()
    conn.close()


def has_any_episodes(podcast_slug: str, db_path: str = _DB_PATH) -> bool:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM episodes WHERE podcast_slug = ? LIMIT 1", (podcast_slug,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def is_processed(podcast_slug: str, episode_url: str, db_path: str = _DB_PATH) -> bool:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM episodes WHERE podcast_slug = ? AND episode_url = ? LIMIT 1",
            (podcast_slug, episode_url),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def mark_processed(
    podcast_slug: str,
    episode_url: str,
    episode_title: str,
    transcript_chars: int,
    db_path: str = _DB_PATH,
):
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO episodes (podcast_slug, episode_url, episode_title, transcript_chars)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(podcast_slug, episode_url) DO UPDATE SET
                episode_title = excluded.episode_title,
                transcript_chars = excluded.transcript_chars,
                processed_at = CURRENT_TIMESTAMP
            """,
            (podcast_slug, episode_url, episode_title, transcript_chars),
        )
        conn.commit()
    finally:
        conn.close()


def load_bot_users(telegram_db_path: str) -> list[int]:
    """Read registered chat IDs from the telegram-channel-monitor's database."""
    conn = sqlite3.connect(telegram_db_path)
    try:
        rows = conn.execute("SELECT chat_id FROM bot_users").fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()
