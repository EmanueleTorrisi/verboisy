# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Source yield caches must follow successful durable productivity events."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from verboisy.core.planner import source_productivity_score
from verboisy.core.research import ResearchRunner


@pytest.mark.parametrize("existing", [False, True])
def test_failed_productivity_write_does_not_publish_or_double_count(existing):
    runner = ResearchRunner.__new__(ResearchRunner)
    runner.rid = "run"
    baseline = {"data.test": {"accepted": 2, "misses": 1}} if existing else {}
    runner.source_productivity = deepcopy(baseline)
    prior_host = runner.source_productivity.get("data.test")
    runner.store = SimpleNamespace(event=MagicMock(side_effect=OSError("Yield journal failed")))

    with pytest.raises(OSError, match="Yield journal failed"):
        runner.record_source_productivity(
            "https://DATA.TEST./page", accepted=1, rejected=1, duplicates=1
        )
    assert runner.source_productivity == baseline
    if existing:
        assert runner.source_productivity["data.test"] is prior_host

    runner.store.event.side_effect = None
    runner.record_source_productivity(
        "https://DATA.TEST./page", accepted=1, rejected=1, duplicates=1
    )
    expected = {"accepted": 3, "misses": 3} if existing else {"accepted": 1, "misses": 2}
    assert runner.source_productivity == {"data.test": expected}
    if existing:
        assert runner.source_productivity["data.test"] is prior_host
    score = source_productivity_score(expected["accepted"], expected["misses"])
    assert runner.source_scores() == {"data.test": score}
    runner.store.event.assert_called_with(
        "run",
        "source_productivity",
        {"host": "data.test", "accepted": 1, "misses": 2, "score": score},
    )
