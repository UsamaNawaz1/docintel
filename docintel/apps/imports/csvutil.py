"""Streaming CSV helpers.

The parser never materialises the file. Callers pull one record at a time.
Encoding is UTF-8 (BOM stripped) with a CP1252 fallback for spreadsheets that
were saved from older Excel. The fallback runs only when the first chunk is
not valid UTF-8; CP1252 can represent every byte, so it is the last resort
rather than a guess among many encodings.
"""

from __future__ import annotations

import codecs
import csv
import io
from collections.abc import Iterator

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> str:
    """Prefix spreadsheet formulas so a downloaded CSV cannot execute them."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def template_csv(headers: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([csv_safe(header) for header in headers])
    return buffer.getvalue().encode("utf-8-sig")


def read_headers(chunks: Iterator[bytes]) -> list[str]:
    lines = _open_lines(chunks)
    reader = csv.reader(lines)
    try:
        header_row = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV file is empty") from exc
    headers = [cell.strip() for cell in header_row]
    if not any(headers):
        raise ValueError("CSV header row is empty")
    return headers


def iter_records(chunks: Iterator[bytes]) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield ``(line_number, row)`` for data rows. Line 1 is the header."""
    lines = _open_lines(chunks)
    reader = csv.reader(lines)
    try:
        header_row = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV file is empty") from exc
    headers = [cell.strip() for cell in header_row]
    if not any(headers):
        raise ValueError("CSV header row is empty")
    for offset, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue
        padded = list(cells) + [""] * max(0, len(headers) - len(cells))
        yield offset, {headers[index]: padded[index].strip() for index in range(len(headers))}


def _open_lines(chunks: Iterator[bytes]) -> Iterator[str]:
    first = next(chunks, b"")

    def replay() -> Iterator[bytes]:
        if first:
            yield first
        yield from chunks

    encoding = "utf-8-sig"
    try:
        first.decode("utf-8-sig")
    except UnicodeDecodeError:
        encoding = "cp1252"
    return _iter_lines(replay(), encoding)


def _iter_lines(chunks: Iterator[bytes], encoding: str) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    pending = ""
    for chunk in chunks:
        pending += decoder.decode(chunk)
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            yield line
    pending += decoder.decode(b"", final=True)
    if pending:
        yield pending
