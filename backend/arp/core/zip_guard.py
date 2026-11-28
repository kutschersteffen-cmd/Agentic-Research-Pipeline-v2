"""Zip-bomb size and compression-ratio guard for untrusted `.xlsx` / `.zip` uploads."""

from __future__ import annotations

import io
import zipfile

MAX_UNZIPPED = 200_000_000
MAX_RATIO, RATIO_MIN_SIZE = 100, 10_000_000


def _check_zip(data: bytes) -> None:
    """Reject zip archives whose inflated size or compression ratio exceeds safe limits."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
    if sum(i.file_size for i in infos) > MAX_UNZIPPED or any(
        i.file_size > RATIO_MIN_SIZE and i.file_size > MAX_RATIO * max(i.compress_size, 1) for i in infos
    ):
        raise ValueError("unreadable file: decompressed size too large")
