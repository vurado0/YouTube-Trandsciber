"""Entrypoint for serverless platforms (Vercel).

Locally the server is started with `uvicorn app:app --app-dir backend`, which
puts `backend/` on the import path so its modules can import each other by bare
name. A serverless platform imports this file from the repository root instead,
so the same directory has to be added here before the app is loaded.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app import app  # noqa: E402  (import must follow the path setup)

__all__ = ["app"]
