import asyncio
import html
import re
import xml.etree.ElementTree as ET

import aiohttp


BASE_URL = "https://podscripts.co"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def fetch_html(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            return await resp.text()
    except asyncio.TimeoutError:
        return None
    except aiohttp.ClientError:
        return None


def extract_episode_links(html_body: str, podcast_slug: str) -> list[str]:
    slug = re.escape(podcast_slug)
    pattern = re.compile(
        rf'href=["\'](?P<href>(?:https://podscripts\.co)?/podcasts/{slug}/[^"\'?#]+)["\']',
        re.IGNORECASE,
    )
    out = []
    for m in pattern.finditer(html_body):
        href = m.group("href")
        if href.startswith("/"):
            href = f"{BASE_URL}{href}"
        href = href.rstrip("/")
        if href == f"{BASE_URL}/podcasts/{podcast_slug}":
            continue
        out.append(href)
    return out


def extract_episode_title(html_body: str, episode_url: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html_body, flags=re.IGNORECASE | re.DOTALL)
    if m:
        title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        title = re.sub(r"\s*[|\-]\s*Podscripts.*$", "", title, flags=re.IGNORECASE)
        # Strip trailing " Transcript and Discussion" suffix podscripts adds
        title = re.sub(r"\s+Transcript\s+and\s+Discussion\s*$", "", title, flags=re.IGNORECASE).strip()
        if title:
            return title
    slug = episode_url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").title()


def extract_transcript(html_body: str) -> str | None:
    text = _html_to_text(html_body)
    block_re = re.compile(
        r"Starting point is (?P<ts>\d{2}:\d{2}:\d{2})\s*(?P<body>.*?)"
        r"(?=Starting point is \d{2}:\d{2}:\d{2}|$)",
        flags=re.DOTALL,
    )
    blocks = list(block_re.finditer(text))
    if not blocks:
        return None

    parts = []
    for b in blocks:
        ts = b.group("ts")
        body = re.sub(r"\s+", " ", b.group("body")).strip()
        parts.append(f"[{ts}]")
        if body:
            parts.append(body)
    return "\n".join(parts).strip()


def extract_rss_episode_items(xml_body: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return []

    out: list[dict[str, str]] = []
    for item in (e for e in root.iter() if _local_name(e.tag) == "item"):
        title = (_find_xml_child_text(item, "title") or "").strip()
        episode_url = (
            _find_xml_child_text(item, "link")
            or _find_xml_child_text(item, "guid")
            or ""
        ).strip()
        audio_url = _find_enclosure_url(item)

        if not audio_url:
            continue
        if not episode_url or not episode_url.startswith("http"):
            episode_url = audio_url

        out.append(
            {
                "episode_title": title or "Untitled Episode",
                "episode_url": episode_url,
                "audio_url": audio_url,
            }
        )
    return out


def _find_enclosure_url(item: ET.Element) -> str:
    for child in list(item):
        if _local_name(child.tag) != "enclosure":
            continue
        url = (child.attrib.get("url") or "").strip()
        if url:
            return url
    return ""


def _find_xml_child_text(parent: ET.Element, child_name: str) -> str:
    for child in list(parent):
        if _local_name(child.tag) != child_name:
            continue
        return (child.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1].lower()
    return tag.lower()


def _html_to_text(html_body: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_body)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\r", "\n")
    text = re.sub(r"\t", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
