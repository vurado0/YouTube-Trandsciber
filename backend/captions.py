"""Fetch and normalise YouTube caption tracks via yt-dlp."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path

import yt_dlp

SUPPORTED = {"en": "English", "de": "Deutsch", "ja": "日本語"}

# Sentence-ish boundaries for the three supported languages.
_SENTENCE_END = re.compile(r"[.!?。！？…]['\")\]」』]?\s*$")
_MAX_CHUNK_SECONDS = 9.0
_MAX_CHUNK_CHARS = 180


class CaptionError(Exception):
    pass


def ytdlp_auth() -> dict:
    """Extra yt-dlp options for getting past YouTube's bot check.

    YouTube refuses requests from datacenter IP ranges with "Sign in to confirm
    you're not a bot", which is why a deployed instance fails where a laptop on
    a home connection succeeds. Supplying cookies from a signed-in account is
    the documented workaround; see the README for what you are accepting if you
    do that. Nothing happens unless YTDLP_COOKIES is set.
    """
    cookies = os.environ.get("YTDLP_COOKIES", "").strip()
    if not cookies:
        return {}

    path = Path(cookies)
    if not path.is_file():
        # Treat the value as the cookie file's contents (how you would pass it
        # through an environment variable on a host with no writable project
        # directory).
        path = Path(tempfile.gettempdir()) / "yt-cookies.txt"
        try:
            path.write_text(cookies, "utf-8")
        except OSError:
            return {}

    return {"cookiefile": str(path)}


def video_id(url: str) -> str:
    """Pull the 11-character video id out of any common YouTube URL shape."""
    patterns = [
        r"(?:v=|/v/|/embed/|/shorts/|youtu\.be/|/live/)([0-9A-Za-z_-]{11})",
        r"^([0-9A-Za-z_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url.strip())
        if match:
            return match.group(1)
    raise CaptionError("That does not look like a YouTube link.")


def canonical_url(url: str) -> str:
    """Rebuild a clean watch URL from the video id.

    Never hand a user-supplied string to yt-dlp directly: it will happily fetch
    any URL, including one pointing at something on the host's own network. We
    extract the 11-character id and build the URL ourselves, so the only thing
    that can ever be fetched is a YouTube video.
    """
    return f"https://www.youtube.com/watch?v={video_id(url)}"


def probe(url: str) -> dict:
    """Return video metadata plus which caption languages are actually usable."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        **ytdlp_auth(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(canonical_url(url), download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise CaptionError(_clean(str(exc))) from exc

    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    available = {}
    for lang in SUPPORTED:
        track = _pick_track(manual, lang)
        if track:
            available[lang] = "manual"
            continue
        if _pick_track(auto, lang):
            available[lang] = "auto"

    return {
        "id": info.get("id"),
        "title": info.get("title") or "Untitled",
        "channel": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail") or "",
        "video_language": (info.get("language") or "").split("-")[0].lower(),
        "captions": available,
        "_manual": manual,
        "_auto": auto,
    }


def fetch(url: str, lang: str, info: dict | None = None) -> dict:
    """Download one caption track and return normalised segments."""
    if lang not in SUPPORTED:
        raise CaptionError(f"Unsupported language: {lang}")

    info = info or probe(url)
    source = "manual"
    track = _pick_track(info["_manual"], lang)
    if not track:
        source = "auto"
        track = _pick_track(info["_auto"], lang)
    if not track:
        raise CaptionError(f"No {SUPPORTED[lang]} captions on this video.")

    raw = _download(track["url"])
    events = _parse_json3(raw)
    if not events:
        raise CaptionError("The caption track came back empty.")

    return {
        "segments": _chunk(events, lang),
        "source": f"youtube-{source}",
        "language": lang,
    }


# --- internals -------------------------------------------------------------


def _pick_track(tracks: dict, lang: str) -> dict | None:
    """Choose the best json3 track for `lang`, ignoring machine translations.

    yt-dlp keys translated auto-captions as `<target>-<source>` (e.g. `de-en` is
    German machine-translated from English), which we never want: those are
    translations of a translation and read badly.
    """
    candidates = []
    for key, formats in tracks.items():
        base = key.split("-")[0].lower()
        if base != lang:
            continue
        suffix = key[len(base) + 1:] if "-" in key else ""
        if suffix and suffix.lower() in SUPPORTED and suffix.lower() != lang:
            continue  # machine translation from another language
        rank = 0 if not suffix else (1 if suffix in ("orig", lang) else 2)
        for fmt in formats:
            if fmt.get("ext") == "json3":
                candidates.append((rank, {"key": key, "url": fmt["url"]}))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _download(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en,de,ja"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_json3(data: dict) -> list[dict]:
    """json3 events -> flat list of {start, end, text, words}."""
    out = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        start = (event.get("tStartMs") or 0) / 1000.0
        duration = (event.get("dDurationMs") or 0) / 1000.0

        words = []
        for seg in segs:
            text = seg.get("utf8", "")
            if not text.strip():
                continue
            words.append(
                {
                    "t": start + (seg.get("tOffsetMs") or 0) / 1000.0,
                    "w": text.replace("\n", " "),
                }
            )
        if not words:
            continue

        text = "".join(word["w"] for word in words)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        out.append({"start": start, "end": start + duration, "text": text, "words": words})

    out.sort(key=lambda event: event["start"])
    return out


def _chunk(events: list[dict], lang: str) -> list[dict]:
    """Merge caption fragments into sentence-sized lines that are easier to study."""
    joiner = "" if lang == "ja" else " "
    chunks: list[dict] = []
    buffer: list[dict] = []

    def flush():
        if not buffer:
            return
        text = joiner.join(event["text"] for event in buffer)
        text = re.sub(r"\s+", " ", text).strip() if lang != "ja" else text.strip()
        words = []
        for index, event in enumerate(buffer):
            for position, word in enumerate(event["words"]):
                surface = word["w"]
                # Events were joined with `joiner`; keep that separator in the
                # word-timed copy too, or words collide across the seam.
                if index and not position and joiner and not surface.startswith(" "):
                    surface = joiner + surface
                words.append({"t": round(word["t"], 3), "w": surface})

        chunks.append(
            {
                "start": round(buffer[0]["start"], 3),
                "end": round(buffer[-1]["end"], 3),
                "text": text,
                "words": words,
            }
        )
        buffer.clear()

    for event in events:
        buffer.append(event)
        span = buffer[-1]["end"] - buffer[0]["start"]
        length = sum(len(item["text"]) for item in buffer)
        if _SENTENCE_END.search(event["text"]) or span >= _MAX_CHUNK_SECONDS or length >= _MAX_CHUNK_CHARS:
            flush()
    flush()
    return chunks


def _clean(message: str) -> str:
    message = re.sub(r"\x1b\[[0-9;]*m", "", message)
    message = message.replace("ERROR: ", "").strip()

    # The bot check is the one failure people actually hit on a hosted
    # instance. yt-dlp's own text is a wall of flags and wiki links, which
    # tells a visitor nothing about what went wrong or whose problem it is.
    if "confirm you" in message and "bot" in message:
        return (
            "YouTube is refusing requests from this server. It blocks the "
            "datacentre addresses that hosting providers use, so this happens "
            "for every video, not just this one. Running the app on your own "
            "machine works normally."
        )

    return f"YouTube rejected that link: {message.splitlines()[0][:260]}"
