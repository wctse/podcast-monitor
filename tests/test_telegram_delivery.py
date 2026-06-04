import asyncio

import main
from notifier import send_error_alert, send_seed_report, send_signal


class RecordingBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


def test_resolve_chat_ids_uses_target_channel_only():
    cfg = {
        "telegram": {
            "target_channel_id": -1003931653025,
            "chat_ids": [111, 222],
            "users_db_path": "/tmp/unused-bot-users.db",
        },
        "admin": {"chat_id": 115436546, "admin_only": True},
    }

    assert main._resolve_chat_ids(cfg) == [-1003931653025]


def test_resolve_chat_ids_ignores_static_and_admin_without_target_channel():
    cfg = {
        "telegram": {"chat_ids": [111, 222]},
        "admin": {"chat_id": 115436546, "admin_only": True},
    }

    assert main._resolve_chat_ids(cfg) == []


def test_resolve_chat_ids_invalid_target_channel_sends_nothing():
    cfg = {"telegram": {"target_channel_id": "not-a-channel"}}

    assert main._resolve_chat_ids(cfg) == []


def test_send_signal_sends_only_to_configured_target_channel():
    bot = RecordingBot()
    analysis = {
        "confidence": 0.9,
        "summary": "Signal summary",
        "tickers": [{"symbol": "ABC", "bias": "bullish", "thesis": "Thesis"}],
    }

    asyncio.run(send_signal(bot, [-1003931653025], "Podcast", "Episode", "https://example.com", analysis))

    assert [message["chat_id"] for message in bot.messages] == [-1003931653025]
    assert bot.messages[0]["parse_mode"] == "HTML"


def test_send_signal_missing_target_channel_sends_nothing():
    bot = RecordingBot()
    analysis = {"confidence": 0.9, "summary": "Signal summary", "tickers": []}

    asyncio.run(send_signal(bot, [], "Podcast", "Episode", "https://example.com", analysis))

    assert bot.messages == []


def test_send_seed_report_sends_to_admin_chat_id():
    bot = RecordingBot()

    asyncio.run(send_seed_report(bot, 115436546, "Podcast", ["https://example.com/episode"]))

    assert [message["chat_id"] for message in bot.messages] == [115436546]
    assert bot.messages[0]["parse_mode"] == "HTML"


def test_send_error_alert_sends_to_admin_chat_id():
    bot = RecordingBot()

    asyncio.run(send_error_alert(bot, 115436546, "⚠️ <b>Error</b>"))

    assert [message["chat_id"] for message in bot.messages] == [115436546]
    assert bot.messages[0]["parse_mode"] == "HTML"


def test_send_error_alert_without_admin_chat_id_sends_nothing():
    bot = RecordingBot()

    asyncio.run(send_error_alert(bot, None, "⚠️ <b>Error</b>"))

    assert bot.messages == []
