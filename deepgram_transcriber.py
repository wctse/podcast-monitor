import asyncio
import logging
import os

import aiohttp


logger = logging.getLogger(__name__)


class DeepgramCreditsError(Exception):
    """Raised when the Deepgram API returns 402 (out of credits)."""


class DeepgramTranscriber:
    def __init__(self, cfg: dict):
        self.api_key = (cfg.get("api_key") or os.getenv("DEEPGRAM_API_KEY") or "").strip()
        self.model = cfg.get("model", "nova-2")
        self.language = cfg.get("language", "en")
        self.timeout_seconds = int(cfg.get("timeout_seconds", 900))
        self.punctuate = bool(cfg.get("punctuate", True))
        self.paragraphs = bool(cfg.get("paragraphs", True))
        self.smart_format = bool(cfg.get("smart_format", True))
        self.utterances = bool(cfg.get("utterances", True))
        self._session: aiohttp.ClientSession | None = None

    async def open(self):
        timeout = aiohttp.ClientTimeout(connect=10, sock_read=self.timeout_seconds)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def transcribe_audio_url(self, audio_url: str) -> str | None:
        """Submit audio URL to Deepgram and wait for the transcript.

        Deepgram fetches and transcribes the audio server-side; no local
        download or ffmpeg required. The connection stays open until done
        (timeout_seconds controls how long to wait).

        Raises DeepgramCreditsError on HTTP 402 (out of credits).
        Returns None on other errors so the caller can retry next scan.
        """
        if not self.api_key:
            logger.error("Deepgram API key is missing. Set deepgram.api_key or DEEPGRAM_API_KEY")
            return None
        if not self._session:
            raise RuntimeError("DeepgramTranscriber.open() must be called before use")

        params = {
            "model": self.model,
            "language": self.language,
            "punctuate": str(self.punctuate).lower(),
            "paragraphs": str(self.paragraphs).lower(),
            "smart_format": str(self.smart_format).lower(),
            "utterances": str(self.utterances).lower(),
        }
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.post(
                "https://api.deepgram.com/v1/listen",
                headers=headers,
                params=params,
                json={"url": audio_url},
            ) as resp:
                if resp.status == 402:
                    raise DeepgramCreditsError(
                        f"Deepgram account is out of credits (HTTP 402) for {audio_url}"
                    )
                if resp.status != 200:
                    logger.error(
                        "Deepgram API error %d for %s: %s",
                        resp.status,
                        audio_url,
                        await resp.text(),
                    )
                    return None
                data = await resp.json()
        except DeepgramCreditsError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Deepgram request failed for %s: %r", audio_url, e)
            return None

        lines = self._render_response(data)
        transcript = "\n".join(line for line in lines if line).strip()
        return transcript or None

    @staticmethod
    def _render_response(response_json: dict) -> list[str]:
        results = response_json.get("results", {})
        utterances = results.get("utterances", [])
        if utterances:
            lines = []
            for u in utterances:
                text = str(u.get("transcript", "")).strip()
                if not text:
                    continue
                ts = _to_hhmmss(float(u.get("start", 0.0)))
                speaker = u.get("speaker")
                if speaker is None:
                    lines.append(f"[{ts}] {text}")
                else:
                    lines.append(f"[{ts}] Speaker {speaker}: {text}")
            return lines

        channels = results.get("channels", [])
        alternatives = channels[0].get("alternatives", []) if channels else []
        transcript = alternatives[0].get("transcript", "").strip() if alternatives else ""
        return [transcript] if transcript else []


def _to_hhmmss(total_seconds: float) -> str:
    total_seconds = max(0, int(total_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
