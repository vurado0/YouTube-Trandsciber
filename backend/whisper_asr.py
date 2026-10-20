"""Speech-to-text fallback for videos with no usable captions.

Optional: if faster-whisper is not installed the app still works, it just
cannot transcribe caption-less videos.
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Callable

import yt_dlp

import captions

# Both of these ship only with the Whisper extra. Without them the app still
# runs, it just cannot transcribe caption-less videos — so the import must not
# be allowed to take the whole server down.
try:
    import numpy as np
    from faster_whisper import WhisperModel

    AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    np = None
    WhisperModel = None
    AVAILABLE = False

MODEL_SIZE = "small"  # good accuracy/speed balance for de/ja on a laptop CPU
_model = None


def _load():
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def download_audio(url: str, target_dir: Path, progress: Callable[[str, int], None]) -> Path:
    """Grab the smallest audio-only stream and convert it to 16 kHz mono wav."""
    out_template = str(target_dir / "audio.%(ext)s")

    def hook(status):
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            percent = int(done / total * 100) if total else 0
            progress("Downloading audio", min(percent, 99))

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "progress_hooks": [hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": "0"}
        ],
        "postprocessor_args": ["-ar", "16000", "-ac", "1"],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([captions.canonical_url(url)])

    files = sorted(target_dir.glob("audio.*"))
    wav = [path for path in files if path.suffix == ".wav"]
    if not wav:
        raise RuntimeError("Could not extract audio from that video.")
    return wav[0]


def read_wav(path: Path) -> "np.ndarray":
    """Read our own 16 kHz mono wav into the float32 array Whisper wants.

    faster-whisper would decode the file itself, but it does that through PyAV,
    whose recent releases no longer accept the arguments it passes. ffmpeg has
    already given us exactly the format Whisper needs, so we skip that path.
    """
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise RuntimeError("Expected 16-bit audio from ffmpeg.")
        frames = handle.readframes(handle.getnframes())
        channels = handle.getnchannels()

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples


def transcribe(
    url: str,
    lang: str,
    duration: int,
    progress: Callable[[str, int], None],
) -> dict:
    if not AVAILABLE:
        raise RuntimeError(
            "No captions on this video, and the offline transcriber is not installed. "
            "Run: ./setup.sh --with-whisper"
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        audio = download_audio(url, tmp_dir, progress)

        progress("Loading speech model", 0)
        model = _load()

        progress("Listening to the audio", 0)
        iterator, info = model.transcribe(
            read_wav(audio),
            language=lang,
            vad_filter=True,
            word_timestamps=True,
            beam_size=5,
        )

        total = duration or info.duration or 0
        segments = []
        for segment in iterator:
            text = segment.text.strip()
            if not text:
                continue
            words = [
                {"t": round(word.start, 3), "w": word.word}
                for word in (segment.words or [])
            ]
            segments.append(
                {
                    "start": round(segment.start, 3),
                    "end": round(segment.end, 3),
                    "text": text,
                    "words": words,
                }
            )
            if total:
                progress("Transcribing", min(int(segment.end / total * 100), 99))

    if not segments:
        raise RuntimeError("The transcriber could not hear any speech in that video.")

    return {"segments": segments, "source": f"whisper-{MODEL_SIZE}", "language": lang}
