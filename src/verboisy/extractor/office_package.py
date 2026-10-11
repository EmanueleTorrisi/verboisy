# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Bounded in-memory OOXML parts; archive members are never extracted or executed."""

import io
import stat
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import PurePosixPath
from xml.etree import ElementTree

from verboisy.extractor.format_errors import DatasetParseError


@contextmanager
def office_package(content: bytes) -> Iterator[zipfile.ZipFile]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            entries = package.infolist()
            if len(entries) > 1024 or sum(item.file_size for item in entries) > 16_777_216:
                raise DatasetParseError("Office archive expansion limit exceeded")
            if len({item.filename for item in entries}) != len(entries):
                raise DatasetParseError("Duplicate office archive member")
            for item in entries:
                # Reject names changed by ZipInfo normalization as well as unsafe
                # paths. Windows turns archive backslashes into forward slashes.
                if (
                    item.orig_filename != item.filename
                    or item.filename.startswith("/")
                    or "\\" in item.filename
                    or ":" in item.filename
                    or ".." in PurePosixPath(item.filename).parts
                    or stat.S_ISLNK(item.external_attr >> 16)
                ):
                    raise DatasetParseError("Unsafe office archive member")
                if item.flag_bits & 1 or item.compress_type not in {
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                }:
                    raise DatasetParseError("Unsupported office archive encoding")
                if item.file_size > max(1, item.compress_size) * 200:
                    raise DatasetParseError("Office archive compression ratio exceeded")
            yield package
    except (zipfile.BadZipFile, RuntimeError, OSError, zlib.error):
        raise DatasetParseError("Malformed office archive") from None


def xml_part(package: zipfile.ZipFile, name: str, max_depth: int) -> ElementTree.Element:
    try:
        content = package.read(name)
        # OOXML parts use UTF-8. DTDs and entity declarations are not needed for
        # these contracts and must be rejected before the XML parser sees them.
        text = content.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise DatasetParseError("Office XML declarations are unsupported")
        root = ElementTree.fromstring(text)
        pending = [(root, 1)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if depth > max_depth or count > 100_000:
                raise DatasetParseError("Office XML structure limit exceeded")
            pending.extend((child, depth + 1) for child in node)
        return root
    except (KeyError, UnicodeError, ElementTree.ParseError):
        raise DatasetParseError("Missing or malformed office XML part") from None
