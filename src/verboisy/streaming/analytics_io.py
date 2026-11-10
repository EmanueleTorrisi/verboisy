# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded analytical shard encoders and byte accounting."""

import gzip
import hashlib
import io
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import Any

from verboisy.streaming.analytics_contract import GROUP_BYTES, GROUP_ROWS, Column, typed_cell
from verboisy.streaming.contract import StreamError


class OutputBudget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.used = 0

    def reserve(self, size: int) -> None:
        if self.used + size > self.maximum:
            raise StreamError("Analytical export exceeds its output byte limit")
        self.used += size


class Sink(io.BufferedWriter):
    """Exclusive, append-only file used by the gzip and Arrow writers."""

    def __init__(self, path: Path, budget: OutputBudget) -> None:
        super().__init__(io.FileIO(path, mode="x"))
        self.path = path
        self.budget = budget
        self.digest = hashlib.sha256()
        self.byte_count = 0

    def write(self, buffer: Any, /) -> int:
        with memoryview(buffer) as payload:
            self.budget.reserve(payload.nbytes)
            written = super().write(payload)
            self.digest.update(payload)
            self.byte_count += written
        return written

    def finish(self) -> dict[str, str | int]:
        self.flush()
        os.fsync(self.fileno())
        return {"name": self.path.name, "bytes": self.byte_count, "sha256": self.digest.hexdigest()}


@contextmanager
def jsonl_writer(sink: Sink) -> Iterator[Callable[[bytes], None]]:
    with gzip.GzipFile(filename="", mode="wb", fileobj=sink, compresslevel=3, mtime=0) as data:

        def write(value: bytes) -> None:
            data.write(value)
            data.write(b"\n")

        yield write


class ParquetEncoder:
    def __init__(self, columns: tuple[Column, ...]) -> None:
        try:
            self.arrow = import_module("pyarrow")
            self.parquet = import_module("pyarrow.parquet")
        except (ImportError, OSError) as error:
            raise StreamError(
                "Parquet needs a working PyArrow installation (26.0.1 tested); "
                "gzip JSONL is available without it"
            ) from error
        self.columns = columns
        self.names = frozenset(column.name for column in columns)
        arrow = self.arrow
        if not arrow.Codec.is_available("zstd"):
            raise StreamError("The installed PyArrow does not support Zstandard compression")
        types = {
            "bool": arrow.bool_(),
            "int64": arrow.int64(),
            "float64": arrow.float64(),
            "string": arrow.string(),
            "json": arrow.string(),
        }
        self.schema = arrow.schema(
            [arrow.field(c.name, types[c.kind], nullable=c.nullable) for c in columns]
        )

    @contextmanager
    def writer(self, sink: Sink) -> Iterator[Callable[[bytes], None]]:
        # A bounded batch and disabled dictionaries limit encoder memory. Shards
        # also bound the amount of row group metadata retained in the footer.
        with self.parquet.ParquetWriter(
            sink, self.schema, compression="zstd", use_dictionary=False, version="2.6"
        ) as output:
            cells: list[list[Any]] = [[] for _ in self.columns]
            size = 0

            def flush() -> None:
                nonlocal size
                arrays = [
                    self.arrow.array(values, type=field.type)
                    for values, field in zip(cells, self.schema, strict=True)
                ]
                batch = self.arrow.RecordBatch.from_arrays(arrays, schema=self.schema)
                output.write_batch(batch)
                for values in cells:
                    values.clear()
                size = 0

            def write(value: bytes) -> None:
                nonlocal size
                row_size = len(value) + 16 * len(cells)
                if cells[0] and (len(cells[0]) >= GROUP_ROWS or size + row_size > GROUP_BYTES):
                    flush()
                record = json.loads(value)
                if record.keys() != self.names:
                    raise StreamError("Parquet requires exactly the declared columns on every row")
                for column, values in zip(self.columns, cells, strict=True):
                    values.append(typed_cell(column, record[column.name]))
                size += row_size

            yield write
            if cells[0]:
                flush()
