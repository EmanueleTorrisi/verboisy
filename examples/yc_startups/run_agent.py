"""Run the public API against a live directory; results depend on the site and model."""

from pathlib import Path

from verboisy import run


def main() -> None:
    result = run(
        goal=(
            "Open https://www.ycombinator.com/companies "
            "and find the five most recently launched AI startups."
        ),
        schema=Path(__file__).with_name("schema.json"),
        export=Path(__file__).with_name("startups.json"),
    )
    print(result.run_id, result.status, len(result.records))
    if not result.completed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
