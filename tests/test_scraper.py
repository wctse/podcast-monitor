import pytest
from scraper import extract_rss_episode_items


MINIMAL_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Episode 1</title>
      <link>https://example.com/ep1</link>
      <guid>https://example.com/ep1-guid</guid>
      <enclosure url="https://cdn.example.com/ep1.mp3" type="audio/mpeg" length="12345"/>
    </item>
  </channel>
</rss>"""

NAMESPACED_RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <item>
      <title>Episode 2</title>
      <link>https://example.com/ep2</link>
      <enclosure url="https://cdn.example.com/ep2.mp3" type="audio/mpeg" length="99"/>
    </item>
  </channel>
</rss>"""

NO_ENCLOSURE_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>No Audio</title>
      <link>https://example.com/no-audio</link>
    </item>
  </channel>
</rss>"""

GUID_ONLY_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <guid>https://example.com/ep3-guid</guid>
      <enclosure url="https://cdn.example.com/ep3.mp3" type="audio/mpeg" length="1"/>
    </item>
  </channel>
</rss>"""

NO_URL_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <enclosure url="https://cdn.example.com/ep4.mp3" type="audio/mpeg" length="1"/>
    </item>
  </channel>
</rss>"""


def test_basic_item_extracted():
    items = extract_rss_episode_items(MINIMAL_RSS)
    assert len(items) == 1
    assert items[0]["episode_title"] == "Episode 1"
    assert items[0]["audio_url"] == "https://cdn.example.com/ep1.mp3"


def test_link_preferred_over_guid():
    items = extract_rss_episode_items(MINIMAL_RSS)
    assert items[0]["episode_url"] == "https://example.com/ep1"


def test_guid_fallback_when_no_link():
    items = extract_rss_episode_items(GUID_ONLY_RSS)
    assert len(items) == 1
    assert items[0]["episode_url"] == "https://example.com/ep3-guid"


def test_audio_url_fallback_when_no_url():
    items = extract_rss_episode_items(NO_URL_RSS)
    assert len(items) == 1
    assert items[0]["episode_url"] == "https://cdn.example.com/ep4.mp3"


NON_URL_GUID_RSS = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <guid>031d9390-4434-11f1-9283-63533352abf3</guid>
      <enclosure url="https://traffic.megaphone.fm/ep5.mp3" type="audio/mpeg" length="1"/>
    </item>
  </channel>
</rss>"""


def test_non_url_guid_falls_back_to_audio_url():
    items = extract_rss_episode_items(NON_URL_GUID_RSS)
    assert len(items) == 1
    assert items[0]["episode_url"] == "https://traffic.megaphone.fm/ep5.mp3"


def test_item_without_enclosure_skipped():
    items = extract_rss_episode_items(NO_ENCLOSURE_RSS)
    assert items == []


def test_namespaced_feed_parsed():
    items = extract_rss_episode_items(NAMESPACED_RSS)
    assert len(items) == 1
    assert items[0]["episode_url"] == "https://example.com/ep2"


def test_malformed_xml_returns_empty():
    items = extract_rss_episode_items("this is not xml <<<")
    assert items == []


def test_empty_string_returns_empty():
    items = extract_rss_episode_items("")
    assert items == []
