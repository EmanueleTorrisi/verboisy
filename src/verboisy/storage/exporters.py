"""
Utilities for exporting extracted data to various formats (JSON, CSV).
"""

import csv
import json
from pathlib import Path
from typing import Any

from verboisy.utils.logger import get_logger

logger = get_logger(__name__)


class DataExporter:
    """Handles exporting list of dictionaries to files."""

    @staticmethod
    def export_json(data: list[dict[str, Any]], filepath: str | Path) -> None:
        """
        Export a list of dictionaries to a JSON file.

        Args:
            data: The list of dicts to export.
            filepath: Destination file path.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("Exported JSON successfully", filepath=str(path), count=len(data))
        except Exception as e:
            logger.error("Failed to export JSON", filepath=str(path), error=str(e))
            raise

    @staticmethod
    def export_csv(data: list[dict[str, Any]], filepath: str | Path) -> None:
        """
        Export a list of dictionaries to a CSV file.
        Flattens nested dicts minimally. Best for flat schemas.

        Args:
            data: The list of dicts to export.
            filepath: Destination file path.
        """
        if not data:
            logger.warning("No data provided to export", filepath=str(filepath))
            return

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Collect all possible headers
        headers: set[str] = set()
        for item in data:
            headers.update(item.keys())

        header_list = sorted(headers)

        try:
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=header_list)
                writer.writeheader()
                for row in data:
                    # Convert nested structures to strings for CSV compatibility
                    processed_row = {
                        k: (json.dumps(v) if isinstance(v, dict | list) else v)
                        for k, v in row.items()
                    }
                    writer.writerow(processed_row)
            logger.info("Exported CSV successfully", filepath=str(path), count=len(data))
        except Exception as e:
            logger.error("Failed to export CSV", filepath=str(path), error=str(e))
            raise
