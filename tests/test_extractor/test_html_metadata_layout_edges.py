# Copyright (c) 2026 Emanuele Torrisi.
# See LICENSE for applicable terms.

"""Keep explicit absence and ordinary rendered HTML distinct from bad layout."""

import unittest

from verboisy.evidence.html_metadata import HtmlMetadataError, HtmlMetadataSpec, literal_metadata
from verboisy.evidence.html_metadata_snapshot import html_metadata_candidate, html_metadata_snapshot

PLAN = HtmlMetadataSpec.model_validate(
    {
        "region": "main",
        "fields": {
            "title": {"selector": "h1"},
            "summary": {"selector": "p.summary", "on_missing": "null"},
            "issued": {"selector": "dl.info", "label": "Issued"},
        },
    }
)
MARKUP = """<!doctype html><html><head><meta charset="utf-8"></head>
<body><main><h1>New<b>ton</b> Guide</h1><br/><br></br>
<p class="summary" aria-hidden="true">private observation</p>
<p class="summary" style="visibility: hidden">another hidden value</p>
<dl class="info">
  <dt>Issued :</dt>
  <dd>12 November 2026</dd>
</dl></main></body></html>"""


class RenderedLayoutTests(unittest.TestCase):
    def test_visible_absence_and_void_tags_do_not_change_the_record(self) -> None:
        row = {"title": "Newton Guide", "summary": None, "issued": "12 November 2026"}
        self.assertEqual(literal_metadata(MARKUP, PLAN), row)
        url = "https://example.test/guide"
        snapshot = html_metadata_snapshot(MARKUP, url, 4096, PLAN)
        self.assertEqual(html_metadata_candidate(snapshot, PLAN).record, row)
        present = MARKUP.replace("<dl class=", '<p class="summary">None</p><dl class=')
        self.assertEqual(literal_metadata(present, PLAN), {**row, "summary": "None"})
        blank = present.replace(">None</p>", "> </p>")
        with self.assertRaisesRegex(HtmlMetadataError, "blank_or_oversized_value"):
            literal_metadata(blank, PLAN)
