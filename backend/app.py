"""YouTube transcript study tool — local web app.

Captions come from YouTube when the video has them; otherwise the audio is
transcribed offline with Whisper. Japanese transcripts get furigana.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import captions
import japanese
import whisper_asr

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)

app = FastAPI(title="Transcript Study")

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class TranscribeRequest(BaseModel):
    url: str
    lang: str = "auto"
    force_whisper: bool = False


@app.get("/api/capabilities")
def capabilities():
    return {
        "whisper": whisper_asr.AVAILABLE,
        "whisper_model": whisper_asr.MODEL_SIZE,
        "furigana": japanese.AVAILABLE,
        "languages": captions.SUPPORTED,
    }


@app.post("/api/probe")
def probe(request: TranscribeRequest):
    try:
        info = captions.probe(request.url)
    except captions.CaptionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {key: value for key, value in info.items() if not key.startswith("_")}


@app.post("/api/transcribe")
def transcribe(request: TranscribeRequest):
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "status": "running",
            "stage": "Looking up the video",
            "percent": 0,
            "created": time.time(),
        }
    thread = threading.Thread(
        target=_run, args=(job_id, request.url, request.lang, request.force_whisper), daemon=True
    )
    thread.start()
    return {"job": job_id}


@app.get("/api/job/{job_id}")
def job(job_id: str):
    with _lock:
        state = _jobs.get(job_id)
    if not state:
        return JSONResponse({"error": "Unknown job."}, status_code=404)
    return state


# --- worker ----------------------------------------------------------------


def _set(job_id: str, **fields):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def _run(job_id: str, url: str, lang: str, force_whisper: bool):
    try:
        info = captions.probe(url)
        meta = {key: value for key, value in info.items() if not key.startswith("_")}

        chosen = _choose_language(lang, info)
        if not chosen:
            raise captions.CaptionError(
                "Pick a language — this video has no English, German or Japanese captions "
                "to auto-detect from."
            )

        _set(job_id, stage=f"Fetching {captions.SUPPORTED[chosen]} captions", percent=5, meta=meta)

        cached = _cache_path(info["id"], chosen, force_whisper)
        if cached.exists():
            result = json.loads(cached.read_text("utf-8"))
            _finish(job_id, meta, result)
            return

        use_captions = not force_whisper and chosen in info["captions"]
        if use_captions:
            result = captions.fetch(url, chosen, info)
        else:
            if not whisper_asr.AVAILABLE:
                raise RuntimeError(
                    f"This video has no {captions.SUPPORTED[chosen]} captions, and the offline "
                    "transcriber is not installed. Run ./setup.sh --with-whisper to enable it."
                )
            result = whisper_asr.transcribe(
                url,
                chosen,
                info.get("duration") or 0,
                lambda stage, percent: _set(job_id, stage=stage, percent=percent),
            )

        _set(job_id, stage="Preparing the text", percent=99)
        if chosen == "ja" and japanese.AVAILABLE:
            japanese.annotate(result["segments"])

        cached.write_text(json.dumps(result, ensure_ascii=False), "utf-8")
        _finish(job_id, meta, result)

    except Exception as exc:  # surfaced to the user verbatim
        _set(job_id, status="error", error=str(exc) or exc.__class__.__name__)


def _finish(job_id: str, meta: dict, result: dict):
    _set(
        job_id,
        status="done",
        stage="Ready",
        percent=100,
        meta=meta,
        result=result,
    )


def _choose_language(lang: str, info: dict) -> str | None:
    if lang in captions.SUPPORTED:
        return lang
    # auto: prefer the video's own language, then whatever captions exist.
    video_language = info.get("video_language")
    if video_language in captions.SUPPORTED:
        return video_language
    for candidate in ("en", "de", "ja"):
        if candidate in info["captions"]:
            return candidate
    return None


def _cache_path(video: str, lang: str, whisper: bool) -> Path:
    suffix = f"{video}.{lang}{'.whisper' if whisper else ''}.json"
    return CACHE / suffix


# --- static ----------------------------------------------------------------


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
