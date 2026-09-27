"""Small in-process rate limits (one web process serves the site, so memory is enough).

- per client IP: every /api request, sliding one-minute window
- per user: expensive calls (charts fetch Binance/Yahoo; too many would get the server's IP blocked)
- per user: concurrent live-update streams
"""
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

IP_PER_MINUTE = int(os.environ.get("RATE_IP_PER_MINUTE", "180"))
CHART_PER_MINUTE = int(os.environ.get("RATE_CHART_PER_MINUTE", "40"))
MAX_STREAMS = int(os.environ.get("RATE_MAX_STREAMS", "3"))

_hits: dict[str, deque] = defaultdict(deque)
_streams: dict[str, int] = defaultdict(int)


def client_ip(request: Request) -> str:
    """Behind the site's own reverse proxy (TRUST_PROXY=1) the right-most X-Forwarded-For entry is the real client."""
    ip = request.client.host if request.client else "unknown"
    if os.environ.get("TRUST_PROXY") == "1":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            ip = fwd.split(",")[-1].strip()
    return ip


def hit(key: str, limit: int, window: float = 60.0, now: float | None = None) -> bool:
    """Pure-ish sliding window: True if allowed (and counted), False if over the limit."""
    now = time.monotonic() if now is None else now
    q = _hits[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    if len(_hits) > 50_000:  # never let the table grow without bound
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > window][:10_000]:
            _hits.pop(k, None)
    return True


def check_user(user_id: str, bucket: str, limit: int):
    if not hit(f"{bucket}:{user_id}", limit):
        raise HTTPException(status_code=429, detail="Çok sık istek gönderildi; bir dakika sonra tekrar dene.")


class StreamSlot:
    """async with StreamSlot(uid): at most MAX_STREAMS open live-update connections per user."""

    def __init__(self, user_id: str):
        self.uid = user_id

    def __enter__(self):
        if _streams[self.uid] >= MAX_STREAMS:
            raise HTTPException(status_code=429, detail="Çok fazla açık sekme; birini kapatıp yenile.")
        _streams[self.uid] += 1
        return self

    def __exit__(self, *exc):
        _streams[self.uid] = max(0, _streams[self.uid] - 1)
        return False
