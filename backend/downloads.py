"""Download a video as MP4 or its audio as MP3."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Callable

import yt_dlp

import captions

KINDS = {
    "mp4": "Video (MP4)",
    "mp3": "Audio (MP3)",
}

# Cap the resolution: 4K files are huge, slow, and rarely what anyone studying
# a language actually wants.
MAX_HEIGHT = 1080


class DownloadError(Exception):
    pass


def prepare(
    url: str,
    kind: str,
    target_dir: Path,
    progress: Callable[[str, int], None],
) -> tuple[Path, str]:
    """Fetch the video into `target_dir`. Returns (path on disk, filename to serve)."""
    if kind not in KINDS:
        raise DownloadError(f"Unknown format: {kind}")

    target_dir.mkdir(parents=True, exist_ok=True)
    label = "video" if kind == "mp4" else "audio"

    def hook(status):
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            progress(f"Downloading {label}", min(int(done / total * 100), 99) if total else 0)
        elif status.get("status") == "finished":
            progress("Converting", 99)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": str(target_dir / "%(title).80B.%(ext)s"),
        "progress_hooks": [hook],
        "restrictfilenames": False,
        "windowsfilenames": True,
    }

    if kind == "mp4":
        opts["format"] = (
            f"bv*[ext=mp4][height<={MAX_HEIGHT}]+ba[ext=m4a]/"
            f"b[ext=mp4][height<={MAX_HEIGHT}]/"
            f"bv*[height<={MAX_HEIGHT}]+ba/b"
        )
        opts["merge_output_format"] = "mp4"
    else:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            {"key": "FFmpegMetadata"},
        ]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(captions.canonical_url(url), download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(_clean(str(exc))) from exc

    wanted = ".mp4" if kind == "mp4" else ".mp3"
    files = [path for path in target_dir.iterdir() if path.suffix.lower() == wanted]
    if not files:
        # yt-dlp fell back to another container (rare, but possible).
        files = [path for path in target_dir.iterdir() if path.is_file()]
    if not files:
        raise DownloadError("The download produced no file.")

    path = max(files, key=lambda item: item.stat().st_size)
    filename = f"{safe_filename(info.get('title') or 'video')}{path.suffix}"
    return path, filename


def safe_filename(title: str) -> str:
    """A filename that survives every OS, without mangling German or Japanese."""
    title = unicodedata.normalize("NFC", title)
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title)
    title = re.sub(r"\s+", " ", title).strip(" .")
    return title[:120] or "video"


def _clean(message: str) -> str:
    message = re.sub(r"\x1b\[[0-9;]*m", "", message).replace("ERROR: ", "").strip()
    return message.split("\n")[0][:300]
