#!/usr/bin/env python3
"""Build an NDA image03 submission CSV from BIDS sessions and metadata tables.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

REQUIRED_TEMPLATE_COLUMNS = {
    "subjectkey",
    "src_subject_id",
    "session_id",
    "interview_date",
    "interview_age",
    "sex",
    "manifest",
    "image_description",
    "scan_type",
    "scan_object",
    "image_modality",
}
TRUE_VALUES = {"1", "true", "yes", "y"}
DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%Y/%m/%d")
AVERAGE_DAYS_PER_MONTH = 365.25 / 12


class PipelineError(Exception):
    """Raised for invalid inputs that prevent a reliable output."""


def read_csv_dicts(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise PipelineError(f"Input CSV does not exist: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PipelineError(f"CSV has no header row: {path}")
        missing = required - set(reader.fieldnames)
        if missing:
            raise PipelineError(
                f"{path.name} is missing required column(s): {', '.join(sorted(missing))}"
            )
        return [
            {str(key): (value or "").strip() for key, value in row.items() if key is not None}
            for row in reader
        ]


def read_template(path: Path) -> tuple[list[str], list[str]]:
    if not path.is_file():
        raise PipelineError(f"NDA template does not exist: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2:
        raise PipelineError("The template must contain the two NDA header rows.")
    if len(rows[0]) != len(rows[1]):
        raise PipelineError("The two template header rows have different column counts.")
    header = [name.strip() for name in rows[1]]
    normalized_header = [name.lower() for name in header]
    if len(set(normalized_header)) != len(normalized_header):
        raise PipelineError("The template contains duplicate field names (ignoring case).")
    missing = REQUIRED_TEMPLATE_COLUMNS - set(normalized_header)
    if missing:
        raise PipelineError(
            "The template is missing required image03 field(s): "
            + ", ".join(sorted(missing))
        )
    return rows[0], header


def parse_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError("Date uses an unrecognized format")


def age_in_months(date_of_birth: str, interview_date: str) -> int | None:
    """Return age rounded to the nearest average calendar month.
    """
    dob = parse_date(date_of_birth)
    visit = parse_date(interview_date)
    if dob is None or visit is None:
        return None
    if visit < dob:
        raise ValueError("interview date is earlier than date of birth")
    elapsed_days = (visit - dob).days
    return math.floor((elapsed_days / AVERAGE_DAYS_PER_MONTH) + 0.5)


def truthy(value: str) -> bool:
    return value.strip().lower() in TRUE_VALUES


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"constant_fields": {}, "sidecar_field_map": {}}
    if not path.is_file():
        raise PipelineError(f"Configuration file does not exist: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Invalid JSON configuration: {exc}") from exc
    if not isinstance(config, dict):
        raise PipelineError("Configuration must be a JSON object.")
    for key in ("constant_fields", "sidecar_field_map"):
        if key not in config:
            config[key] = {}
        if not isinstance(config[key], dict):
            raise PipelineError(f"Configuration key {key!r} must be an object.")
    return config


def format_metadata(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_csv_atomic(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temp_path = Path(handle.name)
        writer = csv.writer(handle)
        writer.writerows(rows)
    temp_path.replace(path)


def build(args: argparse.Namespace) -> tuple[int, int]:
    bids_root = args.bids_root.resolve()
    manifest_dir = args.manifests.resolve()
    if not bids_root.is_dir():
        raise PipelineError(f"BIDS root is not a directory: {bids_root}")
    if not manifest_dir.is_dir():
        raise PipelineError(f"Manifest directory is not a directory: {manifest_dir}")

    participants = read_csv_dicts(
        args.participants,
        {"source_subject_id", "subjectkey", "sex", "date_of_birth", "exclude"},
    )
    visits = read_csv_dicts(
        args.visits, {"source_subject_id", "session_id", "interview_date"}
    )
    first_header, fields = read_template(args.template)
    config = load_config(args.config)

    participant_by_id: dict[str, dict[str, str]] = {}
    for row in participants:
        source_id = row["source_subject_id"]
        if not source_id:
            raise PipelineError("participants.csv contains a blank source_subject_id")
        if source_id in participant_by_id:
            raise PipelineError(f"Duplicate participant mapping for {source_id!r}")
        participant_by_id[source_id] = row

    visit_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in visits:
        key = (row["source_subject_id"], row["session_id"])
        if not all(key):
            raise PipelineError("visits.csv contains a blank participant or session ID")
        if key in visit_by_key:
            raise PipelineError(f"Duplicate visit record for {key!r}")
        visit_by_key[key] = row

    missing: list[list[str]] = [["source_subject_id", "session_id", "issue"]]
    output_rows: list[list[str]] = [first_header, fields]
    session_dirs = sorted(
        path
        for subject_dir in bids_root.glob("sub-*")
        if subject_dir.is_dir()
        for path in subject_dir.glob("ses-*")
        if path.is_dir()
    )
    if not session_dirs:
        raise PipelineError("No BIDS session folders found (expected sub-*/ses-*).")

    # NDA template headers may be lower- or upper-case. Match fields without
    # changing the spelling/case of the supplied template itself.
    normalized_fields = {field.lower() for field in fields}
    constants = {str(k).lower(): format_metadata(v) for k, v in config["constant_fields"].items()}
    sidecar_map = {str(source): str(target).lower() for source, target in config["sidecar_field_map"].items()}
    unknown_config_fields = (set(constants) | set(sidecar_map.values())) - normalized_fields
    if unknown_config_fields:
        raise PipelineError(
            "Configuration references field(s) absent from the supplied template: "
            + ", ".join(sorted(unknown_config_fields))
        )

    warnings: list[str] = []
    for session_dir in session_dirs:
        source_id = session_dir.parent.name.removeprefix("sub-")
        session_id = session_dir.name.removeprefix("ses-")
        participant = participant_by_id.get(source_id)
        if participant is None:
            missing.append([source_id, session_id, "participant mapping not found"])
            continue
        if truthy(participant["exclude"]):
            continue

        visit = visit_by_key.get((source_id, session_id), {})
        visit_date_raw = visit.get("interview_date", "")
        visit_date = ""
        interview_age = ""
        try:
            parsed_visit = parse_date(visit_date_raw)
            if parsed_visit:
                visit_date = parsed_visit.strftime("%m/%d/%Y")
            if participant["date_of_birth"] and parsed_visit:
                calculated_age = age_in_months(participant["date_of_birth"], visit_date_raw)
                interview_age = "" if calculated_age is None else str(calculated_age)
        except ValueError as exc:
            warnings.append(f"{source_id}/{session_id}: {exc}")
        if not visit:
            missing.append([source_id, session_id, "visit record not found"])
        elif not visit_date:
            warnings.append(f"{source_id}/{session_id}: interview date missing or invalid")

        subjectkey = participant["subjectkey"]
        if not subjectkey:
            missing.append([source_id, session_id, "subjectkey/GUID missing"])
        manifest_name = f"sub-{source_id}_ses-{session_id}_manifest.json"
        manifest_value = manifest_name if (manifest_dir / manifest_name).is_file() else ""
        if not manifest_value:
            missing.append([source_id, session_id, "manifest file not found"])

        values: dict[str, str] = {
            "subjectkey": subjectkey,
            "src_subject_id": source_id,
            "session_id": session_id,
            "interview_date": visit_date,
            "interview_age": interview_age,
            "sex": participant["sex"],
            "manifest": manifest_value,
        }
        values.update(constants)

        sidecar_candidates = [
            path for path in session_dir.rglob(args.sidecar_pattern)
            if path.is_file()
            and not path.name.endswith("_manifest.json")
            and path.name not in {"dataset_description.json", "participants.json"}
        ]
        sidecar_candidates.sort()
        sidecar = sidecar_candidates[0] if sidecar_candidates else None
        if sidecar is None:
            warnings.append(f"{source_id}/{session_id}: no sidecar matched {args.sidecar_pattern!r}")
        else:
            if len(sidecar_candidates) > 1:
                warnings.append(
                    f"{source_id}/{session_id}: multiple sidecars matched; using {sidecar.name}"
                )
            try:
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                if not isinstance(metadata, dict):
                    raise ValueError("sidecar JSON must contain an object")
                for source_field, target_field in sidecar_map.items():
                    values[target_field] = format_metadata(metadata.get(source_field, ""))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                warnings.append(f"{source_id}/{session_id}: could not read {sidecar.name}: {exc}")

        output_rows.append([values.get(field.lower(), "") for field in fields])

    if len(output_rows) == 2:
        raise PipelineError("No eligible BIDS sessions produced output rows.")

    write_csv_atomic(args.output, output_rows)
    write_csv_atomic(args.missing_report, missing)

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(f"Wrote {len(output_rows) - 2} image03 row(s) to {args.output}")
    print(f"Wrote {len(missing) - 1} review item(s) to {args.missing_report}")
    return len(output_rows) - 2, len(missing) - 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an NDA image03 CSV from BIDS sessions and normalized metadata tables."
    )
    parser.add_argument("--bids-root", type=Path, required=True, help="Directory containing sub-*/ses-* folders")
    parser.add_argument("--participants", type=Path, required=True, help="CSV with source_subject_id, subjectkey, sex, date_of_birth, exclude")
    parser.add_argument("--visits", type=Path, required=True, help="CSV with source_subject_id, session_id, interview_date")
    parser.add_argument("--manifests", type=Path, required=True, help="Directory containing per-session JSON manifests")
    parser.add_argument("--template", type=Path, required=True, help="Current NDA image03 template with its two header rows")
    parser.add_argument("--config", type=Path, help="Optional JSON configuration for constant and sidecar-derived fields")
    parser.add_argument("--output", type=Path, default=Path("image_03.csv"), help="Output CSV path")
    parser.add_argument("--missing-report", type=Path, default=Path("missing_links.csv"), help="CSV listing missing mappings and manifests")
    parser.add_argument("--sidecar-pattern", default="*_T1w.json", help="Glob pattern for the session JSON sidecar (default: *_T1w.json)")
    return parser.parse_args()


def main() -> int:
    try:
        build(parse_args())
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
