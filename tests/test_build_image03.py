from __future__ import annotations

import csv
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_image03


class BuildImage03Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bids = self.root / "bids"
        self.manifests = self.root / "manifests"
        self.bids.mkdir()
        self.manifests.mkdir()
        session = self.bids / "sub-TEST001" / "ses-01" / "anat"
        session.mkdir(parents=True)
        (session / "sub-TEST001_ses-01_T1w.json").write_text(
            json.dumps({"SoftwareVersions": ["v1", "v2"], "DeviceSerialNumber": "SERIAL-X"}),
            encoding="utf-8",
        )
        (self.manifests / "sub-TEST001_ses-01_manifest.json").write_text(
            '{"files": []}', encoding="utf-8"
        )
        self.participants = self.root / "participants.csv"
        self.participants.write_text(
            "source_subject_id,subjectkey,sex,date_of_birth,exclude\n"
            "TEST001,NDAR_INVDEMO0001,F,01/15/1980,false\n"
            "TEST002,NDAR_INVDEMO0002,M,01/01/1980,true\n",
            encoding="utf-8",
        )
        self.visits = self.root / "visits.csv"
        self.visits.write_text(
            "source_subject_id,session_id,interview_date\nTEST001,01,02/10/2024\n",
            encoding="utf-8",
        )
        self.template = self.root / "template.csv"
        self.template.write_text(
            "image,3,,,,,,,,,,,,\n"
            "subjectkey,src_subject_id,session_id,interview_date,interview_age,sex,manifest,scanner_software_versions_pd,deviceserialnumber,image_description,scan_type,scan_object,image_file_format,image_modality\n",
            encoding="utf-8",
        )
        self.config = self.root / "config.json"
        self.config.write_text(
            json.dumps({
                "constant_fields": {},
                "sidecar_field_map": {
                    "SoftwareVersions": "scanner_software_versions_pd",
                    "DeviceSerialNumber": "deviceserialnumber",
                },
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_age_in_months_uses_nearest_average_month(self):
        self.assertEqual(build_image03.age_in_months("01/15/1980", "02/10/2024"), 529)

    def test_age_rounding_matches_15_and_16_day_boundary(self):
        self.assertEqual(build_image03.age_in_months("01/01/2024", "01/16/2024"), 0)
        self.assertEqual(build_image03.age_in_months("01/01/2024", "01/17/2024"), 1)

    def test_builder_joins_inputs_and_preserves_template_headers(self):
        output = self.root / "image_03.csv"
        report = self.root / "missing_links.csv"
        args = Namespace(
            bids_root=self.bids,
            manifests=self.manifests,
            participants=self.participants,
            visits=self.visits,
            template=self.template,
            config=self.config,
            output=output,
            missing_report=report,
            sidecar_pattern="*_T1w.json",
        )
        count, missing_count = build_image03.build(args)
        self.assertEqual(count, 1)
        self.assertEqual(missing_count, 0)
        with output.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0][0:2], ["image", "3"])
        self.assertEqual(rows[2][1], "TEST001")
        self.assertEqual(rows[2][4], "529")
        self.assertEqual(rows[2][6], "sub-TEST001_ses-01_manifest.json")
        self.assertEqual(rows[2][7], "v1; v2")
        self.assertEqual(rows[2][8], "SERIAL-X")

    def test_template_field_matching_is_case_insensitive(self):
        upper = self.root / "upper_template.csv"
        upper.write_text(
            "image,3,,,,,,,,,,,,\n"
            "SUBJECTKEY,SRC_SUBJECT_ID,SESSION_ID,INTERVIEW_DATE,INTERVIEW_AGE,SEX,MANIFEST,SCANNER_SOFTWARE_VERSIONS_PD,DEVICESERIALNUMBER,IMAGE_DESCRIPTION,SCAN_TYPE,SCAN_OBJECT,IMAGE_FILE_FORMAT,IMAGE_MODALITY\n",
            encoding="utf-8",
        )
        _, fields = build_image03.read_template(upper)
        self.assertEqual(fields[0], "SUBJECTKEY")

    def test_template_requires_core_fields(self):
        bad = self.root / "bad_template.csv"
        bad.write_text("image,3\nsubjectkey,src_subject_id\n", encoding="utf-8")
        with self.assertRaises(build_image03.PipelineError):
            build_image03.read_template(bad)


if __name__ == "__main__":
    unittest.main()
