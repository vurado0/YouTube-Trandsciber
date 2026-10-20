"""YouTube transcript study tool.

Captions come from YouTube when the video has them; otherwise the audio is
transcribed offline with Whisper. Japanese transcripts get furigana. Videos can
also be saved as MP4 or MP3.

Everything that costs real resources — Whisper, downloads — is behind an
environment switch, so a shared instance can run the cheap caption path only.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import captions
import downloads
import japanese
import whisper_asr

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def flag(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def number(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


ENABLE_WHISPER = flag("ENABLE_WHISPER", True) and whisper_asr.AVAILABLE
ENABLE_DOWNLOADS = flag("ENABLE_DOWNLOADS", True)
TRUST_PROXY = flag("TRUST_PROXY", False)

MAX_CONCURRENT = number("MAX_CONCURRENT_JOBS", 2)
RATE_LIMIT = number("RATE_LIMIT_PER_HOUR", 40)
JOB_TTL = number("JOB_TTL_SECONDS", 3600)
FILE_TTL = number("FILE_TTL_SECONDS", 1800)
# 0 means no limit. A shared instance should cap this; Whisper and downloads on
# a three-hour video will tie the box up for a very long time.
MAX_DURATION = number("MAX_DURATION_SECONDS", 0)

WORK = Path(os.environ.get("WORK_DIR", ROOT / "cache"))
CACHE = WORK / "transcripts"
FILES = WORK / "files"
CACHE.mkdir(parents=True, exist_ok=True)
FILES.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Transcript Study")

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_slots = threading.Semaphore(MAX_CONCURRENT)
_hits: dict[str, deque] = {}


class TranscribeRequest(BaseModel):
    url: str
    lang: str = "auto"
    force_whisper: bool = False


class DownloadRequest(BaseModel):
    url: str
    kind: str = "mp4"


# --- limits ----------------------------------------------------------------


def client_ip(request: Request) -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("fly-client-ip") or request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limited(request: Request) -> bool:
    if RATE_LIMIT <= 0:
        return False
    now = time.time()
    key = client_ip(request)
    with _lock:
        hits = _hits.setdefault(key, deque())
        while hits and now - hits[0] > 3600:
            hits.popleft()
        if len(hits) >= RATE_LIMIT:
            return True
        hits.append(now)
        if len(_hits) > 5000:  # keep the table from growing without bound
            for stale in [ip for ip, seen in _hits.items() if not seen or now - seen[-1] > 3600]:
                _hits.pop(stale, None)
    return False


def sweep():
    """Drop finished jobs and their files once they are past their TTL."""
    now = time.time()
    with _lock:
        expired = [
            job_id
            for job_id, state in _jobs.items()
            if now - state.get("created", now) > JOB_TTL
        ]
        for job_id in expired:
            _jobs.pop(job_id, None)

    for folder in FILES.iterdir() if FILES.exists() else []:
        try:
            if now - folder.stat().st_mtime > FILE_TTL:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


# --- endpoints -------------------------------------------------------------


@app.get("/api/capabilities")
def capabilities():
    return {
        "whisper": ENABLE_WHISPER,
        "whisper_model": whisper_asr.MODEL_SIZE,
        "furigana": japanese.AVAILABLE,
        "downloads": ENABLE_DOWNLOADS,
        "download_kinds": downloads.KINDS if ENABLE_DOWNLOADS else {},
        "languages": captions.SUPPORTED,
        "max_duration": MAX_DURATION,
    }


@app.post("/api/probe")
def probe(request: TranscribeRequest):
    try:
        info = captions.probe(request.url)
    except captions.CaptionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {key: value for key, value in info.items() if not key.startswith("_")}


@app.post("/api/transcribe")
def transcribe(body: TranscribeRequest, request: Request):
    return _start(request, _run_transcribe, body.url, body.lang, body.force_whisper)


@app.post("/api/download")
def download(body: DownloadRequest, request: Request):
    if not ENABLE_DOWNLOADS:
        return JSONResponse({"error": "Downloads are switched off on this server."}, status_code=403)
    if body.kind not in downloads.KINDS:
        return JSONResponse({"error": "Unknown format."}, status_code=400)
    return _start(request, _run_download, body.url, body.kind)


@app.get("/api/job/{job_id}")
def job(job_id: str):
    with _lock:
        state = _jobs.get(job_id)
    if not state:
        return JSONResponse({"error": "Unknown job — it may have expired."}, status_code=404)
    return {key: value for key, value in state.items() if not key.startswith("_")}


@app.get("/api/file/{job_id}")
def file(job_id: str):
    with _lock:
        state = _jobs.get(job_id)
    if not state or state.get("status") != "done" or "_path" not in state:
        return JSONResponse({"error": "Nothing to download for that job."}, status_code=404)

    path = Path(state["_path"])
    if not path.is_file():
        return JSONResponse({"error": "That file has already been cleaned up."}, status_code=410)

    return FileResponse(path, filename=state["filename"], media_type="application/octet-stream")


# --- worker ----------------------------------------------------------------


def _start(request: Request, worker, *args):
    sweep()
    if rate_limited(request):
        return JSONResponse(
            {"error": "Too many requests from your address. Try again later."}, status_code=429
        )

    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "status": "running",
            "stage": "Looking up the video",
            "percent": 0,
            "created": time.time(),
        }
    threading.Thread(target=worker, args=(job_id, *args), daemon=True).start()
    return {"job": job_id}


def _set(job_id: str, **fields):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def _too_long(duration: int) -> bool:
    return bool(MAX_DURATION) and duration > MAX_DURATION


def _run_transcribe(job_id: str, url: str, lang: str, force_whisper: bool):
    if not _slots.acquire(timeout=120):
        _set(job_id, status="error", error="The server is busy. Try again in a minute.")
        return
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

        cached = CACHE / f"{info['id']}.{chosen}{'.whisper' if force_whisper else ''}.json"
        if cached.exists():
            _finish(job_id, meta, json.loads(cached.read_text("utf-8")))
            return

        if not force_whisper and chosen in info["captions"]:
            result = captions.fetch(url, chosen, info)
        else:
            if not ENABLE_WHISPER:
                raise RuntimeError(
                    f"This video has no {captions.SUPPORTED[chosen]} captions, and offline "
                    "transcription is switched off on this server."
                )
            if _too_long(info.get("duration") or 0):
                raise RuntimeError(
                    f"That video is too long to transcribe here (limit "
                    f"{MAX_DURATION // 60} minutes)."
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

    except Exception as exc:
        _set(job_id, status="error", error=str(exc) or exc.__class__.__name__)
    finally:
        _slots.release()


def _run_download(job_id: str, url: str, kind: str):
    if not _slots.acquire(timeout=120):
        _set(job_id, status="error", error="The server is busy. Try again in a minute.")
        return
    try:
        info = captions.probe(url)
        if _too_long(info.get("duration") or 0):
            raise downloads.DownloadError(
                f"That video is too long to download here (limit {MAX_DURATION // 60} minutes)."
            )

        _set(job_id, stage=f"Preparing {downloads.KINDS[kind]}", percent=1)
        path, filename = downloads.prepare(
            url,
            kind,
            FILES / job_id,
            lambda stage, percent: _set(job_id, stage=stage, percent=percent),
        )
        _set(
            job_id,
            status="done",
            stage="Ready",
            percent=100,
            filename=filename,
            size=path.stat().st_size,
            kind=kind,
            _path=str(path),
        )
    except Exception as exc:
        shutil.rmtree(FILES / job_id, ignore_errors=True)
        _set(job_id, status="error", error=str(exc) or exc.__class__.__name__)
    finally:
        _slots.release()


def _finish(job_id: str, meta: dict, result: dict):
    _set(job_id, status="done", stage="Ready", percent=100, meta=meta, result=result)


def _choose_language(lang: str, info: dict) -> str | None:
    if lang in captions.SUPPORTED:
        return lang
    video_language = info.get("video_language")
    if video_language in captions.SUPPORTED:
        return video_language
    for candidate in ("en", "de", "ja"):
        if candidate in info["captions"]:
            return candidate
    return None


# --- static ----------------------------------------------------------------


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
