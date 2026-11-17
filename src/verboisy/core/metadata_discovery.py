# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Select one observed HTTPS page per declared literal metadata path."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from urllib.parse import unquote, urlsplit

from verboisy.core.search import MAX_SEARCH_RESULTS
from verboisy.evidence.models import TaskSpec
from verboisy.evidence.snapshot import canonical_url
from verboisy.product import SourcePolicy
from verboisy.utils.exceptions import VerboisyError

_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_PATH_PATTERN = re.compile(r"/(?!/)[!-~]{0,2047}")


@dataclass(frozen=True)
class MetadataSourceScope:
    host: str
    paths: tuple[str, ...]
    excluded_paths: tuple[str, ...]

    @classmethod
    def from_task(cls, task: TaskSpec) -> MetadataSourceScope:
        if len(task.allowed_hosts) != 1:
            raise VerboisyError("HTML metadata discovery requires one explicit HTTPS host")
        (host,) = task.allowed_hosts
        labels = host.split(".")
        if (
            len(host) > 253
            or len(labels) < 2
            or labels[-1].isdigit()
            or any(not _HOST_LABEL.fullmatch(label) for label in labels)
        ):
            raise VerboisyError("HTML metadata discovery requires a canonical DNS host")
        paths = tuple(task.include_paths)
        excluded = tuple(task.exclude_paths)
        if (
            not paths
            or len(paths) > MAX_SEARCH_RESULTS
            or len(set(paths)) != len(paths)
            or task.target_records != len(paths)
            or task.max_pages < len(paths)
            or any(not _PATH_PATTERN.fullmatch(path) for path in (*paths, *excluded))
        ):
            raise VerboisyError(
                "HTML metadata discovery requires 1 to "
                f"{MAX_SEARCH_RESULTS} distinct path patterns and one target per path"
            )
        scope = cls(host, paths, excluded)
        scope.check_policy(SourcePolicy(avoid=tuple(task.avoided_hosts)))
        return scope

    def check_policy(self, policy: SourcePolicy) -> None:
        if not policy.permits(f"https://{self.host}/"):
            raise VerboisyError("The HTML metadata discovery host conflicts with the source policy")

    def query(self, goal: str) -> str:
        return f"site:{self.host} {goal}"

    def paths_for(self, url: str) -> tuple[str, ...]:
        if canonical_url(url) != url:
            return ()
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc != self.host
            or parts.query
            or parts.fragment
            or any(fnmatchcase(parts.path, path) for path in self.excluded_paths)
        ):
            return ()
        decoded = unquote(parts.path)
        if (
            decoded.count("/") != parts.path.count("/")
            or "\\" in decoded
            or any(part in (".", "..") for part in decoded.split("/"))
        ):
            return ()
        return tuple(path for path in self.paths if fnmatchcase(parts.path, path))

    def select(self, urls: Iterable[str]) -> list[str]:
        """Return selected URLs in declared order; never guess among matches."""
        selected: dict[str, str] = {}
        for url in urls:
            paths = self.paths_for(url)
            if not paths:
                raise VerboisyError("HTML metadata discovery contains a source outside its scope")
            if len(paths) != 1 or selected.setdefault(paths[0], url) != url:
                raise VerboisyError("HTML metadata discovery found ambiguous sources for a path")
        if len(selected) != len(self.paths):
            raise VerboisyError("HTML metadata discovery did not find every declared path")
        return [selected[path] for path in self.paths]
