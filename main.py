import asyncio
import logging
import os
import ssl
import sys

import aiohttp
import yaml

from analyzer import LLMAnalyzer
from db import has_any_episodes, init_db, is_processed, load_bot_users, mark_processed
from notifier import send_seed_report, send_signal
from scraper import (
    extract_episode_links,
    extract_episode_title,
    extract_transcript,
    fetch_html,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _resolve_chat_ids(cfg: dict) -> list[int]:
    admin_cfg = cfg.get("admin", {})
    admin_id = admin_cfg.get("chat_id")
    if admin_cfg.get("admin_only") and admin_id:
        logger.info("Admin-only mode: sending to admin chat_id=%s only", admin_id)
        return [int(admin_id)]

    tg = cfg.get("telegram", {})
    db_path = tg.get("users_db_path")
    if db_path:
        expanded = os.path.expanduser(db_path)
        if os.path.exists(expanded):
            ids = load_bot_users(expanded)
            logger.info("Loaded %d chat ID(s) from %s", len(ids), expanded)
            return ids
        else:
            logger.warning("users_db_path not found: %s — falling back to chat_ids", expanded)
    ids = [int(x) for x in tg.get("chat_ids", [])]
    logger.info("Using %d configured chat ID(s)", len(ids))
    return ids


def _make_ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


async def _scan_podcast(
    session: aiohttp.ClientSession,
    podcast: dict,
    podcasts_cfg: dict,
    db_path: str,
    analyzer: LLMAnalyzer,
    bot,
    chat_ids: list[int],
    admin_chat_id: int | None = None,
):
    slug = (podcast.get("slug") or "").strip().lower()
    if not slug:
        logger.warning("Skipping podcast with no slug: %s", podcast)
        return

    name = podcast.get("name", slug)
    max_pages = int(podcast.get("max_pages_per_scan", podcasts_cfg.get("max_pages_per_scan", 2)))
    max_chars = int(podcast.get("max_transcript_chars", podcasts_cfg.get("max_transcript_chars", 100000)))
    threshold = float(podcast.get("confidence_threshold", podcasts_cfg.get("confidence_threshold", 0.7)))
    source_url = f"https://podscripts.co/podcasts/{slug}/"

    episode_urls: list[str] = []
    for page in range(1, max_pages + 1):
        url = source_url if page == 1 else f"{source_url}?page={page}"
        page_html = await fetch_html(session, url)
        if not page_html:
            if page == 1:
                logger.warning("Could not fetch index for %s", name)
            break
        episode_urls.extend(extract_episode_links(page_html, slug))

    deduped = list(dict.fromkeys(episode_urls))

    # Cold-start: seed all existing episodes without analyzing them
    if not has_any_episodes(slug, db_path):
        logger.info("First scan for %s: seeding %d episode(s) without analyzing", name, len(deduped))
        for url in deduped:
            mark_processed(slug, url, "", 0, db_path)
        if admin_chat_id:
            await send_seed_report(bot, admin_chat_id, name, deduped)
        return

    new_urls = [u for u in deduped if not is_processed(slug, u, db_path)]
    if not new_urls:
        logger.info("No new episodes for %s", name)
        return

    logger.info("Found %d new episode(s) for %s", len(new_urls), name)

    for episode_url in reversed(new_urls):
        await _process_episode(
            session, slug, name, episode_url, max_chars, threshold,
            db_path, analyzer, bot, chat_ids,
        )


async def _process_episode(
    session: aiohttp.ClientSession,
    slug: str,
    podcast_name: str,
    episode_url: str,
    max_chars: int,
    threshold: float,
    db_path: str,
    analyzer: LLMAnalyzer,
    bot,
    chat_ids: list[int],
):
    page_html = await fetch_html(session, episode_url)
    if not page_html:
        logger.warning("Failed to fetch episode: %s", episode_url)
        return

    episode_title = extract_episode_title(page_html, episode_url)
    transcript = extract_transcript(page_html)

    if not transcript:
        logger.warning("No transcript found for: %s — skipping", episode_url)
        mark_processed(slug, episode_url, episode_title, 0, db_path)
        return

    transcript = transcript[:max_chars]
    logger.info("Analyzing '%s' (%d chars)...", episode_title, len(transcript))

    # Mark processed before the LLM call so a timeout doesn't cause re-processing
    mark_processed(slug, episode_url, episode_title, len(transcript), db_path)

    result = await analyzer.analyze(transcript, episode_title=episode_title)
    if not result:
        logger.warning("Analysis failed for: %s", episode_url)
        return

    if result.get("is_signal") and result.get("confidence", 0) >= threshold:
        logger.info(
            "Signal (%.0f%%): %s — %s",
            result["confidence"] * 100, podcast_name, episode_title,
        )
        await send_signal(bot, chat_ids, podcast_name, episode_title, episode_url, result)
    else:
        logger.info(
            "No signal (%.0f%%): %s — %s",
            result.get("confidence", 0) * 100, podcast_name, episode_title,
        )


async def main():
    cfg = _load_config()

    db_path = os.path.expanduser(cfg.get("data", {}).get("db_path", "data/episodes.db"))
    init_db(db_path)

    analyzer = LLMAnalyzer(cfg["llm"])

    from telegram import Bot
    bot = Bot(token=cfg["telegram"]["bot_token"])
    chat_ids = _resolve_chat_ids(cfg)
    admin_chat_id = cfg.get("admin", {}).get("chat_id")
    if admin_chat_id:
        admin_chat_id = int(admin_chat_id)

    if not chat_ids:
        logger.warning("No chat IDs found — signals will not be sent")

    podcasts_cfg = cfg.get("podcasts", {})
    sources = [p for p in podcasts_cfg.get("sources", []) if p.get("enabled", True)]
    poll_interval = int(podcasts_cfg.get("poll_interval_seconds", 3600))

    if not sources:
        logger.error("No podcast sources configured. Check config.yaml.")
        return

    logger.info(
        "Podcast monitor starting: %d source(s), poll every %ds",
        len(sources), poll_interval,
    )

    ssl_ctx = _make_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    http_timeout = aiohttp.ClientTimeout(
        connect=10,
        sock_read=int(podcasts_cfg.get("http_timeout_seconds", 30)),
    )

    async with aiohttp.ClientSession(connector=connector, timeout=http_timeout) as session:
        await analyzer.open()
        try:
            while True:
                for podcast in sources:
                    try:
                        await _scan_podcast(
                            session, podcast, podcasts_cfg, db_path,
                            analyzer, bot, chat_ids,
                            admin_chat_id=admin_chat_id,
                        )
                    except Exception as e:
                        logger.error("Scan failed for %s: %r", podcast.get("name"), e, exc_info=True)
                logger.info("Scan complete. Sleeping %ds...", poll_interval)
                await asyncio.sleep(poll_interval)
        finally:
            await analyzer.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped.")
        sys.exit(0)
