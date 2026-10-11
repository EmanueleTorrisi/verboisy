# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Display defaults are inspectable and cannot override a saved run implicitly."""

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner
from verboisy.api import arun
from verboisy.cli.main import app
from verboisy.core.research import ResearchRunner
from verboisy.llm.client import LLMClient
from verboisy.presentation import PresentationPreferences, preferences
from verboisy.presentation_config import resolve_preferences
from verboisy.storage.research import ResearchStore
from verboisy.utils.config import Settings
from verboisy.utils.exceptions import VerboisyError

from tests.test_storage.test_presentation_export import SCHEMA, saved

ENV_NAMES = ("VERBOISY_MASS_UNIT", "VERBOISY_LENGTH_UNIT", "VERBOISY_DATE_FORMAT")


@pytest.fixture(autouse=True)
def isolate_display_environment(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_builtin_defaults_and_original_imports_remain_compatible():
    assert Settings(_env_file=None).presentation_defaults() == PresentationPreferences()
    assert preferences({}).model_dump() == {
        "mass_unit": "kg",
        "length_unit": "m",
        "date_format": "dmy",
    }


@pytest.mark.parametrize(
    "saved_values,overrides,expected",
    [
        (None, {}, {"mass_unit": "lb", "length_unit": "ft", "date_format": "iso"}),
        (
            {"mass_unit": "kg", "length_unit": "m", "date_format": "dmy"},
            {},
            {"mass_unit": "kg", "length_unit": "m", "date_format": "dmy"},
        ),
        ({"mass_unit": "kg"}, {}, {"mass_unit": "kg", "length_unit": "ft", "date_format": "iso"}),
        (
            {"mass_unit": "kg", "length_unit": "m", "date_format": "dmy"},
            {"date_format": "mdy"},
            {"mass_unit": "kg", "length_unit": "m", "date_format": "mdy"},
        ),
    ],
)
def test_precedence_and_backfill_are_field_specific(saved_values, overrides, expected):
    defaults = PresentationPreferences(mass_unit="lb", length_unit="ft", date_format="iso")
    assert resolve_preferences(defaults, saved_values, overrides).model_dump() == expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("display_mass_unit", "stone"),
        ("display_length_unit", "yards"),
        ("display_date_format", "strftime"),
    ],
)
def test_settings_reject_unsupported_defaults(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_environment_and_dotenv_defaults(monkeypatch, tmp_path):
    path = tmp_path / "display.env"
    path.write_text("VERBOISY_MASS_UNIT=lb\nVERBOISY_LENGTH_UNIT=ft\nVERBOISY_DATE_FORMAT=iso\n")
    assert Settings(_env_file=path).presentation_defaults() == PresentationPreferences(
        mass_unit="lb", length_unit="ft", date_format="iso"
    )
    monkeypatch.setenv("VERBOISY_DATE_FORMAT", "mdy")
    assert Settings(_env_file=path).presentation_defaults().date_format == "mdy"
    assert (
        Settings(_env_file=path, display_date_format="dmy").presentation_defaults().date_format
        == "dmy"
    )


@pytest.mark.asyncio
async def test_first_run_uses_defaults_but_resumes_keep_snapshot(tmp_path, monkeypatch):
    async def completed(self, max_steps):
        self.store.finish(self.rid, "COMPLETED", "target_met", 0, 0)
        return "COMPLETED", "target_met"

    monkeypatch.setattr(ResearchRunner, "run", completed)
    provider = AsyncMock(side_effect=AssertionError("No provider request needed"))
    monkeypatch.setattr(LLMClient, "complete_json", provider)
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "new.db"),
        search_provider="disabled",
        display_mass_unit="lb",
        display_length_unit="ft",
        display_date_format="iso",
    )
    result = await arun(
        goal="Measurements",
        schema=SCHEMA,
        task={"seed_urls": ["https://example.test/"]},
        config=config,
    )
    store = ResearchStore(config.sqlite_db_path, read_only=True)
    before = store.events(result.run_id, "presentation_preferences")
    assert before[0]["payload"] == config.presentation_defaults().model_dump()
    store.close()
    changed = config.model_copy(update={"display_mass_unit": "kg", "display_date_format": "mdy"})
    await arun(resume=result.run_id, config=changed)
    store = ResearchStore(config.sqlite_db_path, read_only=True)
    assert store.events(result.run_id, "presentation_preferences") == before
    store.close()
    provider.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_override_is_saved_and_survives_environment_changes(tmp_path, monkeypatch):
    path, rid, _ = saved(tmp_path)
    provider = AsyncMock(side_effect=AssertionError("No provider request needed"))
    monkeypatch.setattr(LLMClient, "complete_json", provider)
    config = Settings(
        _env_file=None,
        sqlite_db_path=str(path),
        search_provider="disabled",
        display_mass_unit="lb",
        display_date_format="iso",
    )
    first = await arun(resume=rid, config=config)
    assert first.records[0]["weight"] == "100 - 120 lb"
    assert first.records[0]["date"] == "2026-10-08"
    changed = await arun(resume=rid, config=config, mass_unit="kg")
    assert changed.records[0]["weight"] == "45.359237 - 54.431084 kg"
    again = await arun(resume=rid, config=config)
    assert again.records == changed.records
    store = ResearchStore(str(path), read_only=True)
    assert len(store.events(rid, "presentation_preferences")) == 2
    store.close()
    provider.assert_not_called()


@pytest.mark.asyncio
async def test_mutated_invalid_default_fails_before_ledger_creation(tmp_path):
    path = tmp_path / "missing.db"
    config = Settings(_env_file=None, sqlite_db_path=str(path)).model_copy(
        update={"display_mass_unit": "secret-invalid"}
    )
    with pytest.raises(VerboisyError, match="Display preferences") as error:
        await arun(resume="missing", config=config)
    assert "secret-invalid" not in str(error.value)
    assert not path.exists()


def test_configuration_command_exposes_only_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VERBOISY_MASS_UNIT", "lb")
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-secret")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "never-open.db"))

    def forbid(*args, **kwargs):
        raise AssertionError("Configuration inspection must not open a ledger")

    monkeypatch.setattr(ResearchStore, "__init__", forbid)
    result = CliRunner().invoke(app, ["presentation-config"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["scope"] == "configured_defaults"
    assert report["defaults"] == {"mass_unit": "lb", "length_unit": "m", "date_format": "dmy"}
    assert report["precedence"][0] == "explicit_run_options"
    assert "private-test-secret" not in result.output
    assert str(tmp_path) not in result.output
    assert not (tmp_path / "never-open.db").exists()


def test_configuration_command_rejects_invalid_choices_without_echo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VERBOISY_MASS_UNIT", "private-invalid-value")
    result = CliRunner().invoke(app, ["presentation-config"])
    assert result.exit_code == 1
    assert "VERBOISY_MASS_UNIT" in result.output
    assert "private-invalid-value" not in result.output
    assert not (tmp_path / "verboisy.db").exists()
