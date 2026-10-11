# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.


def test_replace_pointer_value_rejects_scalar_intermediate():
    from verboisy.storage.research import (
        _replace_pointer_value,
    )

    record = {
        "population": 100,
    }

    assert (
        _replace_pointer_value(
            record,
            "/population/value",
            200,
        )
        is False
    )

    assert record == {
        "population": 100,
    }


def test_replace_pointer_rejects_scalar_during_traversal():
    from verboisy.storage.research import (
        _replace_pointer_value,
    )

    record = {
        "outer": 123,
    }

    assert (
        _replace_pointer_value(
            record,
            "/outer/value",
            456,
        )
        is False
    )

    assert record == {
        "outer": 123,
    }


def test_replace_pointer_value_rejects_scalar_mid_path():
    from verboisy.storage.research import (
        _replace_pointer_value,
    )

    record = {
        "outer": 123,
    }

    assert not _replace_pointer_value(
        record,
        "/outer/middle/value",
        456,
    )

    assert record == {
        "outer": 123,
    }
