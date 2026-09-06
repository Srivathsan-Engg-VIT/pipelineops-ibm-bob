from __future__ import annotations

import os

MAX_RETRIES: int = int(os.environ.get("RENDER_MAX_RETRIES", 3))
BACKOFF_BASE_SECONDS: float = float(os.environ.get("RENDER_BACKOFF_BASE", 1.0))
