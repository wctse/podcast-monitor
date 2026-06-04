import os
import tempfile

from analyzer import DEFAULT_PROMPT, LLMAnalyzer


BASE_CFG = {
    "base_url": "https://example.com/v1",
    "model": "test-model",
}


def test_uses_prompt_file_when_present():
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write("FILE PROMPT")
        path = f.name

    try:
        cfg = {
            **BASE_CFG,
            "prompt_file": path,
            "prompt": "INLINE PROMPT",
        }
        analyzer = LLMAnalyzer(cfg)
        assert analyzer.prompt == "FILE PROMPT"
    finally:
        os.unlink(path)


def test_falls_back_to_inline_prompt_when_file_missing():
    cfg = {
        **BASE_CFG,
        "prompt_file": "/tmp/does-not-exist-prompt-file.txt",
        "prompt": "INLINE PROMPT",
    }
    analyzer = LLMAnalyzer(cfg)
    assert analyzer.prompt == "INLINE PROMPT"


def test_falls_back_to_default_prompt_when_no_file_or_inline():
    cfg = {
        **BASE_CFG,
        "prompt_file": "/tmp/does-not-exist-prompt-file.txt",
    }
    analyzer = LLMAnalyzer(cfg)
    assert analyzer.prompt == DEFAULT_PROMPT
