"""One-shot test: fetch and analyze the most recent episode of each configured podcast.

Uses a temporary DB so production episode history is not affected.
Results sent to telegram.target_channel_id only.
"""
import asyncio
import logging
import os
import sys

import aiohttp

import main as m
from analyzer import LLMAnalyzer
from db import init_db
from deepgram_transcriber import DeepgramCreditsError, DeepgramTranscriber
from scraper import (
    extract_episode_links,
    extract_rss_episode_items,
    fetch_html,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

TEST_DB = "data/test_latest.db"


async def run():
    cfg = m._load_config()

    os.makedirs("data", exist_ok=True)
    init_db(TEST_DB)

    from telegram import Bot
    bot = Bot(token=cfg["telegram"]["bot_token"])
    chat_ids = m._resolve_chat_ids(cfg)

    logger.info("Sending to %d target channel(s): %s", len(chat_ids), chat_ids)

    podcasts_cfg = cfg.get("podcasts", {})
    sources = [p for p in podcasts_cfg.get("sources", []) if p.get("enabled", True)]

    uses_rss_deepgram = any(
        (p.get("transcript_method") or "podscripts").strip().lower() == "rss_deepgram"
        for p in sources
    )
    deepgram_cfg = cfg.get("deepgram", {})
    deepgram_transcriber = DeepgramTranscriber(deepgram_cfg) if uses_rss_deepgram else None

    ssl_ctx = m._make_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    http_timeout = aiohttp.ClientTimeout(
        connect=10,
        sock_read=int(podcasts_cfg.get("http_timeout_seconds", 30)),
    )

    analyzer = LLMAnalyzer(cfg["llm"])

    async with aiohttp.ClientSession(connector=connector, timeout=http_timeout) as session:
        await analyzer.open()
        if deepgram_transcriber:
            await deepgram_transcriber.open()
        try:
            for podcast in sources:
                name = podcast.get("name", podcast.get("slug", ""))
                slug = (podcast.get("slug") or "").strip().lower()
                transcript_method = (podcast.get("transcript_method") or "podscripts").strip().lower()
                max_chars = int(podcast.get("max_transcript_chars", podcasts_cfg.get("max_transcript_chars", 100000)))
                threshold = float(podcast.get("confidence_threshold", podcasts_cfg.get("confidence_threshold", 0.7)))

                logger.info("=" * 60)
                logger.info("Testing: %s  [%s]", name, transcript_method)
                logger.info("=" * 60)

                try:
                    if transcript_method == "rss_deepgram":
                        await _test_rss_deepgram(
                            session, podcast, podcasts_cfg, name, slug,
                            max_chars, threshold, deepgram_transcriber,
                            analyzer, bot, chat_ids, TEST_DB,
                        )
                    else:
                        await _test_podscripts(
                            session, name, slug, max_chars, threshold,
                            analyzer, bot, chat_ids, TEST_DB,
                        )
                except Exception as e:
                    logger.error("Test failed for %s: %r", name, e, exc_info=True)
        finally:
            await analyzer.close()
            if deepgram_transcriber:
                await deepgram_transcriber.close()

    logger.info("Test complete. You can delete data/test_latest.db when done.")


async def _test_podscripts(
    session, name, slug, max_chars, threshold,
    analyzer, bot, chat_ids, db_path,
):
    source_url = f"https://podscripts.co/podcasts/{slug}/"
    logger.info("Fetching episode list from %s", source_url)
    page_html = await fetch_html(session, source_url)
    if not page_html:
        logger.error("Could not fetch index page for %s", name)
        return

    episode_urls = extract_episode_links(page_html, slug)
    if not episode_urls:
        logger.error("No episode links found for %s", name)
        return

    latest_url = episode_urls[0]
    logger.info("Most recent episode: %s", latest_url)

    await m._process_episode(
        session=session,
        slug=slug,
        podcast_name=name,
        episode_url=latest_url,
        max_chars=max_chars,
        threshold=threshold,
        db_path=db_path,
        analyzer=analyzer,
        bot=bot,
        chat_ids=chat_ids,
    )


async def _test_rss_deepgram(
    session, podcast, podcasts_cfg, name, slug,
    max_chars, threshold, deepgram_transcriber,
    analyzer, bot, chat_ids, db_path,
):
    if not deepgram_transcriber:
        logger.warning("Deepgram transcriber not configured — skipping %s", name)
        return
    if not deepgram_transcriber.api_key:
        logger.warning(
            "Deepgram API key missing — skipping %s. "
            "Add deepgram.api_key to config.yaml or set DEEPGRAM_API_KEY.",
            name,
        )
        return

    rss_url = (podcast.get("rss_url") or "").strip()
    if not rss_url:
        logger.warning("No rss_url for %s — skipping", name)
        return

    logger.info("Fetching RSS feed from %s", rss_url)
    rss_xml = await fetch_html(session, rss_url)
    if not rss_xml:
        logger.error("Could not fetch RSS feed for %s", name)
        return

    items = extract_rss_episode_items(rss_xml)
    if not items:
        logger.error("No items found in RSS feed for %s", name)
        return

    latest = items[0]
    logger.info(
        "Most recent episode: %s\n  URL: %s\n  Audio: %s",
        latest["episode_title"], latest["episode_url"], latest["audio_url"],
    )

    try:
        await m._process_rss_episode(
            slug=slug,
            podcast_name=name,
            episode_url=latest["episode_url"],
            episode_title=latest["episode_title"],
            audio_url=latest["audio_url"],
            max_chars=max_chars,
            threshold=threshold,
            db_path=db_path,
            analyzer=analyzer,
            deepgram_transcriber=deepgram_transcriber,
            bot=bot,
            chat_ids=chat_ids,
        )
    except DeepgramCreditsError:
        logger.error("Deepgram out of credits")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)
