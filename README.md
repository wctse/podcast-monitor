# Podcast Monitor

Polls podcast sources for new episodes, extracts transcripts, runs them through an LLM to extract investment signals, and forwards results to Telegram.

Companion to [Telegram Channel Monitor](https://github.com/wctse/Telegram-channel-monitor). Uses the same bot token, but sends podcast alerts only to the configured Telegram channel.

## How it works

1. Polls configured podcast sources (Podscripts or RSS)
2. Extracts transcripts via the source's configured method
3. Sends the full transcript to an LLM (OpenRouter or Ollama) for single-pass analysis
4. Forwards a digest to `telegram.target_channel_id` if the confidence threshold is met

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
- `telegram.target_channel_id` — the Telegram channel ID that receives all normal outbound alerts

**3. Add podcast sources**

Edit the `podcasts.sources` list in `config.yaml`.

For Podscripts-backed podcasts:

```yaml
podcasts:
  sources:
    - name: "The Compound and Friends"
      slug: "the-compound-and-friends"
      enabled: true
      confidence_threshold: 0.7
```

For RSS + Deepgram podcasts (e.g. Forward Guidance via Megaphone):

```yaml
podcasts:
  sources:
    - name: "Forward Guidance"
      slug: "forward-guidance"
      enabled: true
      transcript_method: "rss_deepgram"
      rss_url: "https://feeds.megaphone.fm/forwardguidance"
      confidence_threshold: 0.7

deepgram:
  api_key: "6b97067ee132a7f05053e7e593e5d685b418b103"
  model: "nova-2"
  language: "en"
  segment_seconds: 600
  timeout_seconds: 180
  punctuate: true
  paragraphs: true
  smart_format: true
  utterances: true
```

`rss_deepgram` requires `ffmpeg` and `ffprobe` in your PATH for chunking and timestamp offset handling.

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
| `podcasts.sources[].transcript_method` | `podscripts` | `podscripts` or `rss_deepgram` |
| `podcasts.sources[].rss_url` | — | Required when `transcript_method` is `rss_deepgram` |
| `deepgram.api_key` | — | Deepgram API key (or use `DEEPGRAM_API_KEY`) |
| `deepgram.model` | `nova-2` | Deepgram transcription model |
| `deepgram.segment_seconds` | `600` | Audio chunk size passed to `ffmpeg` |
| `llm.provider` | `api` | `api` for OpenRouter/OpenAI-compatible, `ollama` for local |
| `llm.model` | — | Model name (e.g. `qwen/qwen3.5-9b` for OpenRouter) |
| `llm.timeout` | `360` | LLM request timeout in seconds |
| `telegram.target_channel_id` | — | Telegram channel ID for all normal outbound messages |
| `admin.chat_id` | `null` | Optional admin command authorization chat ID if bot commands are added |

Per-source overrides: `max_pages_per_scan`, `max_transcript_chars`, and `confidence_threshold` can all be set on individual sources to override the top-level defaults.

## Project structure

```
main.py          — entry point, polling loop
scraper.py       — fetches and parses podscripts.co HTML
deepgram_transcriber.py — RSS enclosure download + chunked Deepgram transcription
analyzer.py      — LLM client, single-pass transcript analysis
notifier.py      — formats and sends Telegram digest messages
db.py            — SQLite episode tracking
config.yaml      — your local config (gitignored)
config.yaml.example
requirements.txt
```
