import logging
from html import escape

logger = logging.getLogger(__name__)

_BIAS_ICON = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}


def _bias_icon(bias: str) -> str:
    return _BIAS_ICON.get(bias.lower(), "⚪")


def render_message(
    podcast_name: str,
    episode_title: str,
    episode_url: str,
    analysis: dict,
) -> str:
    confidence = analysis.get("confidence", 0.0)
    summary = analysis.get("summary", "")
    tickers = analysis.get("tickers", [])

    ticker_lines = []
    for t in tickers:
        icon = _bias_icon(t["bias"])
        thesis = t["thesis"]
        ticker_lines.append(
            f"{icon} <b>{escape(t['symbol'])}</b> — {escape(thesis)}"
        )

    tickers_block = "\n".join(ticker_lines) if ticker_lines else "  (no specific tickers)"

    return (
        f"🎙 <b>{escape(podcast_name)}</b>\n"
        f"📺 {escape(episode_title)}\n"
        f"🔗 {episode_url}\n\n"
        f"<b>Summary:</b> {escape(summary)}\n\n"
        f"<b>Investment views ({confidence:.0%} confidence):</b>\n"
        f"{tickers_block}"
    )


async def send_signal(
    bot,
    chat_ids: list[int],
    podcast_name: str,
    episode_title: str,
    episode_url: str,
    analysis: dict,
):
    if not chat_ids:
        logger.warning("No chat IDs configured — signal not sent")
        return

    message = render_message(podcast_name, episode_title, episode_url, analysis)

    for chat_id in chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
            logger.info("Sent to chat_id=%d", chat_id)
        except Exception as e:
            logger.error("Failed to send to chat_id=%d: %s", chat_id, e)


async def send_seed_report(
    bot,
    admin_chat_id: int,
    podcast_name: str,
    episode_urls: list[str],
):
    """Send a first-seeding summary to the admin."""
    lines = [f"🌱 <b>First scan: {escape(podcast_name)}</b>"]
    lines.append(f"Seeded {len(episode_urls)} existing episode(s) — these will not be analyzed.\n")
    for url in episode_urls[:20]:
        lines.append(f"• {url}")
    if len(episode_urls) > 20:
        lines.append(f"... and {len(episode_urls) - 20} more")
    lines.append("\nMonitoring is now active. New episodes will be analyzed and forwarded.")

    message = "\n".join(lines)
    try:
        await bot.send_message(chat_id=admin_chat_id, text=message, parse_mode="HTML")
        logger.info("Sent seed report to admin chat_id=%d", admin_chat_id)
    except Exception as e:
        logger.error("Failed to send seed report to admin: %s", e)
