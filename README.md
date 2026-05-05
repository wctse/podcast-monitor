# Podcast Monitor

Polls podcast transcript sites for new episodes, runs them through an LLM to extract investment signals, and forwards results to Telegram.

Companion to [Telegram Channel Monitor](https://github.com/wctse/Telegram-channel-monitor). Shares the same bot and registered users — anyone who signed up there receives podcast alerts here too, with no separate registration.

## How it works

1. Polls [podscripts.co](https://podscripts.co) for new episodes from configured podcasts
2. Fetches and parses the episode transcript
3. Sends the full transcript to an LLM (OpenRouter or Ollama) for single-pass analysis
4. Forwards a digest to all registered Telegram users if the confidence threshold is met

On first run, all existing episodes are seeded as processed without analysis to prevent a historical flood.

## Setup

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Configure**

```bash
cp config.yaml.example config.yaml
```

Fill in `config.yaml`:

- `llm.api_key` — your OpenRouter (or compatible) API key
- `telegram.bot_token` — the same bot token used by Telegram Channel Monitor
- `telegram.users_db_path` — path to the telegram-channel-monitor `messages.db` (default: `../telegram-channel-monitor/data/messages.db`)

**3. Add podcast sources**

Edit the `podcasts.sources` list in `config.yaml`. Each source needs a `slug` matching the podcast's URL on podscripts.co:

```yaml
podcasts:
  sources:
    - name: "The Compound and Friends"
      slug: "the-compound-and-friends"
      enabled: true
      confidence_threshold: 0.7
```

**4. Run**

```bash
python main.py
```

## Configuration reference

| Key | Default | Description |
|-----|---------|-------------|
| `podcasts.poll_interval_seconds` | `3600` | How often to check for new episodes |
| `podcasts.max_pages_per_scan` | `2` | Pages of episode listings to scan per poll |
| `podcasts.max_transcript_chars` | `100000` | Transcript length cap sent to LLM |
| `podcasts.confidence_threshold` | `0.7` | Minimum confidence to forward a signal |
| `llm.provider` | `api` | `api` for OpenRouter/OpenAI-compatible, `ollama` for local |
| `llm.model` | — | Model name (e.g. `qwen/qwen3.5-9b` for OpenRouter) |
| `llm.timeout` | `360` | LLM request timeout in seconds |
| `telegram.users_db_path` | — | Path to telegram-channel-monitor DB to inherit registered users |

Per-source overrides: `max_pages_per_scan`, `max_transcript_chars`, and `confidence_threshold` can all be set on individual sources to override the top-level defaults.

## Project structure

```
main.py          — entry point, polling loop
scraper.py       — fetches and parses podscripts.co HTML
analyzer.py      — LLM client, single-pass transcript analysis
notifier.py      — formats and sends Telegram digest messages
db.py            — SQLite episode tracking, reads users from telegram-channel-monitor
config.yaml      — your local config (gitignored)
config.yaml.example
requirements.txt
```
