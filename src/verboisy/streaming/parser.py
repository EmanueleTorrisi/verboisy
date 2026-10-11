# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""One-record-at-a-time text parsing with physical-line and complete-record bounds."""

import csv
import io
import json
from collections.abc import Iterator
from typing import Any, BinaryIO

from verboisy.extractor.dataset import SourceRow, parse_dataset
from verboisy.streaming.contract import StreamError


class LimitedLines:
    """Bound quoted multiline CSV records before the CSV reader accumulates them."""

    def __init__(self, stream: io.TextIOWrapper, ceiling: int):
        self.stream = stream
        self.ceiling = ceiling
        self.used = 0
        self.number = 0

    def __iter__(self) -> "LimitedLines":
        return self

    def __next__(self) -> str:
        line = self.stream.readline(self.ceiling + 1)
        if not line:
            raise StopIteration
        if "\x00" in line:
            raise StreamError("NUL byte in streaming text")
        self.used += len(line.encode("utf-8"))
        self.number += 1
        if self.used > self.ceiling:
            raise StreamError("Streaming source record byte limit exceeded")
        return line


def source_rows(stream: BinaryIO, fmt: str, ceiling: int) -> Iterator[SourceRow]:
    """Preserve CSV strings and JSONL types without reading the entire asset."""
    text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
    lines = LimitedLines(text, ceiling)
    try:
        if fmt in {"csv", "tsv"}:
            reader = csv.reader(lines, strict=True, delimiter="\t" if fmt == "tsv" else ",")
            headers = next(reader, None)
            if (
                not headers
                or len(headers) > 1000
                or any(not h.strip() for h in headers)
                or len(set(headers)) != len(headers)
                or headers[0].lstrip().lower().startswith(("<html", "<!doctype html", "<?xml"))
            ):
                raise StreamError("Streaming tables require unique nonempty text headers")
            lines.used = 0
            index = 0
            while True:
                first = lines.number + 1
                cells = next(reader, None)
                if cells is None:
                    break
                if len(cells) != len(headers):
                    raise StreamError("Streaming table row width differs from header")
                index += 1
                yield _row(
                    index, dict(zip(headers, cells, strict=True)), first, lines.number, ceiling
                )
                lines.used = 0
        else:
            index = 0
            for line in lines:
                if fmt == "jsonl":
                    if not line.strip():
                        lines.used = 0
                        continue
                    values = (
                        parse_dataset(line.encode("utf-8"), "jsonl", max_bytes=ceiling)
                        .rows[0]
                        .values
                    )
                else:
                    values = {"text": line.removesuffix("\n").removesuffix("\r")}
                index += 1
                yield _row(index, values, lines.number, lines.number, ceiling)
                lines.used = 0
            if index == 0:
                raise StreamError("Empty streaming text asset")
    except (UnicodeError, csv.Error, ValueError) as error:
        raise StreamError(f"Malformed streaming text ({type(error).__name__})") from None
    finally:
        text.close()


def _row(index: int, values: dict[str, Any], first: int, last: int, ceiling: int) -> SourceRow:
    encoded = json.dumps(values, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > ceiling:
        raise StreamError("Streaming decoded record byte limit exceeded")
    return SourceRow(index, None, first, last, encoded)
