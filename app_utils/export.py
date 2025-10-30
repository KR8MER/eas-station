"""Shared helpers for generating CSV exports."""

from __future__ import annotations

import csv
import io
from typing import Iterable, Mapping, MutableMapping, Optional, Sequence


def _resolve_fieldnames(
    rows: Sequence[Mapping[str, object]] | Iterable[Mapping[str, object]],
    fieldnames: Optional[Sequence[str]] = None,
) -> Sequence[str]:
    if fieldnames:
        return [str(name) for name in fieldnames]

    collected: MutableMapping[str, None] = {}
    for row in rows:
        for key in row.keys():
            key_str = str(key)
            if key_str not in collected:
                collected[key_str] = None
    return list(collected.keys())


def generate_csv(
    rows: Sequence[Mapping[str, object]] | Iterable[Mapping[str, object]],
    *,
    fieldnames: Optional[Sequence[str]] = None,
    include_header: bool = True,
) -> str:
    """Return a CSV payload for the provided row dictionaries."""

    serializable_rows = list(rows)
    headers = _resolve_fieldnames(serializable_rows, fieldnames=fieldnames)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")

    if include_header:
        writer.writeheader()

    for row in serializable_rows:
        writer.writerow({name: row.get(name, "") for name in headers})

    return buffer.getvalue()


__all__ = ["generate_csv"]
