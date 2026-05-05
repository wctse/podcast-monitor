import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from deepgram_transcriber import DeepgramTranscriber, _to_hhmmss


def _make_utterances_response(*utterances):
    return {"results": {"utterances": list(utterances)}}


def _make_channels_response(transcript: str):
    return {
        "results": {
            "utterances": [],
            "channels": [{"alternatives": [{"transcript": transcript}]}],
        }
    }


class TestRenderResponse:
    def test_utterances_with_speaker(self):
        resp = _make_utterances_response(
            {"start": 0.5, "transcript": "Hello world", "speaker": 0},
            {"start": 61.0, "transcript": "Good point", "speaker": 1},
        )
        lines = DeepgramTranscriber._render_response(resp)
        assert lines == [
            "[00:00:00] Speaker 0: Hello world",
            "[00:01:01] Speaker 1: Good point",
        ]

    def test_utterances_without_speaker(self):
        resp = _make_utterances_response(
            {"start": 30.0, "transcript": "No speaker here"},
        )
        lines = DeepgramTranscriber._render_response(resp)
        assert lines == ["[00:00:30] No speaker here"]

    def test_empty_utterance_transcript_skipped(self):
        resp = _make_utterances_response(
            {"start": 0.0, "transcript": ""},
            {"start": 5.0, "transcript": "  "},
            {"start": 10.0, "transcript": "Real content", "speaker": 0},
        )
        lines = DeepgramTranscriber._render_response(resp)
        assert len(lines) == 1
        assert "Real content" in lines[0]

    def test_channels_fallback_when_no_utterances(self):
        resp = _make_channels_response("Full transcript here")
        lines = DeepgramTranscriber._render_response(resp)
        assert lines == ["Full transcript here"]

    def test_empty_channels_returns_empty(self):
        resp = {"results": {"utterances": [], "channels": []}}
        lines = DeepgramTranscriber._render_response(resp)
        assert lines == []

    def test_empty_response_returns_empty(self):
        lines = DeepgramTranscriber._render_response({})
        assert lines == []


class TestToHhmmss:
    def test_zero(self):
        assert _to_hhmmss(0) == "00:00:00"

    def test_seconds_only(self):
        assert _to_hhmmss(45.7) == "00:00:45"

    def test_minutes_and_seconds(self):
        assert _to_hhmmss(90) == "00:01:30"

    def test_hours(self):
        assert _to_hhmmss(3661) == "01:01:01"

    def test_negative_clamped_to_zero(self):
        assert _to_hhmmss(-5) == "00:00:00"
