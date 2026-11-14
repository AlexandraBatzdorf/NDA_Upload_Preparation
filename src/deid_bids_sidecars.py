#!/usr/bin/env python3
"""Remove a defined set of potentially identifying fields from BIDS JSON sidecars. Particularly useful for multisite data, as it anonymizes institution names while preserving differentiation between sites. 

Update DEFAULT_SITE_PATTERN to correspond to your site's participant labels use another convention to indicate site. If a participant ID does not match the specified pattern, the InstitutionName field will be stripped and left blank.

This is targeted metadata redaction, not a complete de-identification solution.
By default the program performs a dry run; use --write only on a working copy.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Pattern

DEFAULT_FIELDS_TO_REMOVE = (
    "ProcedureStepDescription",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "PatientID",
    "PatientName",
    "AccessionNumber",
    "ReferringPhysicianName",
    "OperatorsName",
)
DEFAULT_SITE_PATTERN = r"sub-(?P<site>M\d{3})[A-Za-z0-9]*"


def atomic_write_json(path: Path, payload: dict) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp_path.replace(path)


def find_sidecars(root: Path, pattern: str) -> list[Path]:
    excluded_names = {"dataset_description.json", "participants.json"}
    return sorted(
        path
        for path in root.rglob(pattern)
        if path.is_file()
        and path.name not in excluded_names
        and not path.name.endswith("_manifest.json")
    )


def redact_file(
    path: Path,
    fields_to_remove: set[str],
    site_regex: Pattern[str],
    site_prefix: str,
    write: bool,
) -> tuple[bool, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"Unable to parse {path}: {exc}"]
    if not isinstance(payload, dict):
        return False, [f"Skipping {path}: top-level JSON value is not an object"]

    changed = False
    notes: list[str] = []
    for field in fields_to_remove:
        if field in payload:
            payload.pop(field)
            changed = True

    if "InstitutionName" in payload:
        match = site_regex.search(str(path))
        if match and "site" in match.groupdict():
            replacement = f"{site_prefix}{match.group('site')}"
            if payload["InstitutionName"] != replacement:
                payload["InstitutionName"] = replacement
                changed = True
        else:
            # Prefer removing the institution value to leaving a potentially identifying name.
            payload.pop("InstitutionName")
            changed = True
            notes.append(f"No site label found for {path.name}; removed InstitutionName")

    if changed and write:
        atomic_write_json(path, payload)
    return changed, notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Redact selected fields in BIDS JSON sidecars (not full de-identification)."
    )
    parser.add_argument("bids_root", type=Path, help="Root of a working copy of a BIDS dataset")
    parser.add_argument("--pattern", default="*.json", help="Sidecar filename glob (default: *.json)")
    parser.add_argument(
        "--site-regex",
        default=DEFAULT_SITE_PATTERN,
        help=("Regex applied to each path; include a named 'site' capture group. "
              f"Default: {DEFAULT_SITE_PATTERN}"),
    )
    parser.add_argument("--site-prefix", default="Site_", help="Prefix for replacement InstitutionName")
    parser.add_argument(
        "--remove-field",
        action="append",
        default=[],
        help="Additional top-level JSON key to remove; may be supplied more than once",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write changes in place. Without this flag, only report proposed changes.",
    )
    args = parser.parse_args()

    root = args.bids_root.resolve()
    if not root.is_dir():
        print(f"ERROR: BIDS root is not a directory: {root}", file=sys.stderr)
        return 2
    try:
        site_regex = re.compile(args.site_regex)
    except re.error as exc:
        print(f"ERROR: invalid --site-regex: {exc}", file=sys.stderr)
        return 2
    if "site" not in site_regex.groupindex:
        print("ERROR: --site-regex must contain a named capture group (?P<site>...)", file=sys.stderr)
        return 2

    fields_to_remove = set(DEFAULT_FIELDS_TO_REMOVE) | set(args.remove_field)
    sidecars = find_sidecars(root, args.pattern)
    if not sidecars:
        print("No JSON sidecars matched the requested pattern.")
        return 0

    changed_count = 0
    errors = 0
    for path in sidecars:
        changed, notes = redact_file(
            path, fields_to_remove, site_regex, args.site_prefix, args.write
        )
        if changed:
            changed_count += 1
        for note in notes:
            print(f"WARNING: {note}", file=sys.stderr)
        if any(note.startswith("Unable to parse") or note.startswith("Skipping") for note in notes):
            errors += 1

    mode = "Updated" if args.write else "Would update"
    print(f"{mode} {changed_count} of {len(sidecars)} JSON sidecar(s).")
    if not args.write:
        print("Dry run only; no files were changed. Re-run with --write on a working copy to apply changes.")
    print("Reminder: this removes only the configured keys; it does not guarantee full de-identification.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
