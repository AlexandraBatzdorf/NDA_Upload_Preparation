from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deid_bids_sidecars import redact_file, DEFAULT_FIELDS_TO_REMOVE, DEFAULT_SITE_PATTERN


class RedactSidecarTests(unittest.TestCase):
    def test_dry_run_does_not_change_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sub-TEST001" / "anat" / "sub-TEST001_T1w.json"
            path.parent.mkdir(parents=True)
            original = {
                "PatientName": "SYNTHETIC PERSON",
                "InstitutionName": "Example Hospital",
                "SoftwareVersions": "1.0",
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            changed, notes = redact_file(
                path,
                set(DEFAULT_FIELDS_TO_REMOVE),
                re.compile(DEFAULT_SITE_PATTERN),
                "Site_",
                False,
            )
            self.assertTrue(changed)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_write_removes_fields_and_replaces_institution(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sub-TEST001" / "anat" / "sub-TEST001_T1w.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"PatientName": "SYNTHETIC PERSON", "InstitutionName": "Example Hospital"}),
                encoding="utf-8",
            )
            changed, _ = redact_file(
                path,
                set(DEFAULT_FIELDS_TO_REMOVE),
                re.compile(DEFAULT_SITE_PATTERN),
                "Site_",
                True,
            )
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(changed)
            self.assertNotIn("PatientName", result)
            self.assertEqual(result["InstitutionName"], "Site_TEST001")

    def test_missing_site_label_removes_institution_name(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sub-UNKNOWN" / "anat" / "sub-UNKNOWN_T1w.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"InstitutionName": "Example Hospital"}), encoding="utf-8")
            changed, notes = redact_file(
                path,
                set(DEFAULT_FIELDS_TO_REMOVE),
                re.compile(DEFAULT_SITE_PATTERN),
                "Site_",
                True,
            )
            self.assertTrue(changed)
            self.assertNotIn("InstitutionName", json.loads(path.read_text(encoding="utf-8")))
            self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
