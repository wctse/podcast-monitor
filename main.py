import asyncio
import logging
import os
import ssl
import sys

import aiohttp
import yaml

from analyzer import LLMAnalyzer
from db import has_any_episodes, init_db, is_processed, mark_processed
from deepgram_transcriber import DeepgramCreditsError, DeepgramTranscriber
from notifier import send_error_alert, send_seed_report, send_signal
from scraper import (
    extract_episode_links,
    extract_rss_episode_items,
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
    tg = cfg.get("telegram", {})
    target_channel_id = tg.get("target_channel_id")
    if target_channel_id in (None, ""):
        logger.warning("telegram.target_channel_id is missing — normal Telegram signals will not be sent")
        return []
    try:
        return [int(target_channel_id)]
    except (TypeError, ValueError):
        logger.warning("telegram.target_channel_id is invalid: %r — normal Telegram signals will not be sent", target_channel_id)
        return []


def _make_ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


async def _seed_episodes(
    slug: str,
    name: str,
    episodes: list[tuple[str, str]],
    db_path: str,
    bot,
    admin_chat_id: int | None,
) -> None:
    urls = [url for url, _ in episodes]
    logger.info("First scan for %s: seeding %d episode(s) without analyzing", name, len(episodes))
    for url, title in episodes:
        mark_processed(slug, url, title, 0, db_path)
    if admin_chat_id:
        await send_seed_report(bot, admin_chat_id, name, urls)


async def _scan_podcast(
    session: aiohttp.ClientSession,
    podcast: dict,
    podcasts_cfg: dict,
    db_path: str,
    analyzer: LLMAnalyzer,
    deepgram_transcriber: DeepgramTranscriber | None,
    bot,
    chat_ids: list[int],
    admin_chat_id: int | None = None,
    error_alerts_enabled: bool = False,
):
    slug = (podcast.get("slug") or "").strip().lower()
    if not slug:
        logger.warning("Skipping podcast with no slug: %s", podcast)
        return

    name = podcast.get("name", slug)
    max_pages = int(podcast.get("max_pages_per_scan", podcasts_cfg.get("max_pages_per_scan", 2)))
    max_chars = int(podcast.get("max_transcript_chars", podcasts_cfg.get("max_transcript_chars", 100000)))
    threshold = float(podcast.get("confidence_threshold", podcasts_cfg.get("confidence_threshold", 0.7)))
    transcript_method = (podcast.get("transcript_method") or "podscripts").strip().lower()

    if transcript_method == "rss_deepgram":
        rss_url = (podcast.get("rss_url") or "").strip()
        if not rss_url:
            logger.warning("Skipping %s: transcript_method=rss_deepgram requires rss_url", name)
            return
        if not deepgram_transcriber:
            logger.warning("Skipping %s: Deepgram transcriber is not configured", name)
            return

        rss_xml = await fetch_html(session, rss_url)
        if not rss_xml:
            logger.warning("Could not fetch RSS feed for %s", name)
            return

        episode_items = extract_rss_episode_items(rss_xml)
        deduped_items: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for item in episode_items:
            episode_url = item.get("episode_url", "")
            if not episode_url or episode_url in seen_urls:
                continue
            seen_urls.add(episode_url)
            deduped_items.append(item)

        if not has_any_episodes(slug, db_path):
            await _seed_episodes(
                slug, name,
                [(item["episode_url"], item.get("episode_title", "")) for item in deduped_items],
                db_path, bot, admin_chat_id,
            )
            return

        new_items = [item for item in deduped_items if not is_processed(slug, item["episode_url"], db_path)]
        if not new_items:
            logger.info("No new episodes for %s", name)
            return

        logger.info("Found %d new episode(s) for %s", len(new_items), name)
        for item in reversed(new_items):
            try:
                await _process_rss_episode(
                    slug=slug,
                    podcast_name=name,
                    episode_url=item["episode_url"],
                    episode_title=item.get("episode_title", "Untitled Episode"),
                    audio_url=item["audio_url"],
                    max_chars=max_chars,
                    threshold=threshold,
                    db_path=db_path,
                    analyzer=analyzer,
                    deepgram_transcriber=deepgram_transcriber,
                    bot=bot,
                    chat_ids=chat_ids,
                )
            except DeepgramCreditsError:
                logger.error("Deepgram account is out of credits — halting transcription for this scan")
                if error_alerts_enabled:
                    await send_error_alert(
                        bot,
                        admin_chat_id,
                        "⚠️ <b>Deepgram out of credits</b> — podcast transcription paused. Top up your account to resume.",
                    )
                return
        return

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

    if not has_any_episodes(slug, db_path):
        await _seed_episodes(slug, name, [(url, "") for url in deduped], db_path, bot, admin_chat_id)
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

    await _analyze_episode_transcript(
        slug=slug,
        podcast_name=podcast_name,
        episode_url=episode_url,
        episode_title=episode_title,
        transcript=transcript,
        max_chars=max_chars,
        threshold=threshold,
        db_path=db_path,
        analyzer=analyzer,
        bot=bot,
        chat_ids=chat_ids,
    )


async def _process_rss_episode(
    slug: str,
    podcast_name: str,
    episode_url: str,
    episode_title: str,
    audio_url: str,
    max_chars: int,
    threshold: float,
    db_path: str,
    analyzer: LLMAnalyzer,
    deepgram_transcriber: DeepgramTranscriber,
    bot,
    chat_ids: list[int],
):
    transcript = await deepgram_transcriber.transcribe_audio_url(audio_url)
    if not transcript:
        logger.warning("No transcript produced for: %s — will retry next scan", episode_url)
        return

    await _analyze_episode_transcript(
        slug=slug,
        podcast_name=podcast_name,
        episode_url=episode_url,
        episode_title=episode_title,
        transcript=transcript,
        max_chars=max_chars,
        threshold=threshold,
        db_path=db_path,
        analyzer=analyzer,
        bot=bot,
        chat_ids=chat_ids,
    )


async def _analyze_episode_transcript(
    slug: str,
    podcast_name: str,
    episode_url: str,
    episode_title: str,
    transcript: str,
    max_chars: int,
    threshold: float,
    db_path: str,
    analyzer: LLMAnalyzer,
    bot,
    chat_ids: list[int],
):

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
    error_alerts_enabled = bool(cfg.get("error_alerts", {}).get("enabled", False))
    if not chat_ids:
        logger.warning("No target channel configured — normal Telegram signals will not be sent")

    podcasts_cfg = cfg.get("podcasts", {})
    sources = [p for p in podcasts_cfg.get("sources", []) if p.get("enabled", True)]
    poll_interval = int(podcasts_cfg.get("poll_interval_seconds", 3600))
    uses_rss_deepgram = any(
        (p.get("transcript_method") or "podscripts").strip().lower() == "rss_deepgram"
        for p in sources
    )
    deepgram_transcriber = DeepgramTranscriber(cfg.get("deepgram", {})) if uses_rss_deepgram else None

    if deepgram_transcriber and not deepgram_transcriber.api_key:
        logger.error("Deepgram API key is missing. rss_deepgram sources will not be transcribed.")
        if error_alerts_enabled:
            await send_error_alert(
                bot,
                admin_chat_id,
                "⚠️ <b>Deepgram API key missing</b> — rss_deepgram sources will be skipped until set.",
            )

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
        if deepgram_transcriber:
            await deepgram_transcriber.open()
        try:
            while True:
                for podcast in sources:
                    try:
                        await _scan_podcast(
                            session, podcast, podcasts_cfg, db_path,
                            analyzer, deepgram_transcriber, bot, chat_ids,
                            admin_chat_id=admin_chat_id,
                            error_alerts_enabled=error_alerts_enabled,
                        )
                    except Exception as e:
                        logger.error("Scan failed for %s: %r", podcast.get("name"), e, exc_info=True)
                logger.info("Scan complete. Sleeping %ds...", poll_interval)
                await asyncio.sleep(poll_interval)
        finally:
            await analyzer.close()
            if deepgram_transcriber:
                await deepgram_transcriber.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped.")
        sys.exit(0)
