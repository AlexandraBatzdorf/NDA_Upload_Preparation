# NDA Submission Workflow

Configurable example of preparing session-level metadata for NIMH Data Archive (NDA) submissions using BIDS-compliant data.

1. **Prepare Metadata:** join participant and visit metadata to BIDS participant/session folders, calculate age in months at each study visit, retrieve selected scanner metadata from JSON sidecars, and populate an NDA submission template.
2. **De-identify Sidecars:** identify and remove a configured set of potentially identifying metadata fields from JSON sidecars; particularly useful for multisite data.

Scripts use the Python standard library. A small Bash entry point is included for convenience.

> **Note:**  
> This is a generalized demonstration, not an NDA-approved submission tool and not a complete de-identification workflow. Example data and manifest files are synthetic and for demonstration purposes only. The sidecar script removes only specified top-level JSON keys; it does not inspect image headers, filenames, directory names, free text, dates, or every possible source of identifying information, as it assumes a first-pass anonymization script has been run at the time of export and is designed to strip potentially identifying information from multisite study data (e.g., institution name). Always follow your institution's data-sharing, privacy, and review procedures.

## Workflow

```text
BIDS participant/session folders ───┐
                                    │
Participant mapping CSV ────────────┼──> build_image03.py ──> image_03.csv
                                    │                         missing_links.csv
Visit date CSV ─────────────────────┤
                                    │
NDA image03 template ───────────────┤
                                    │
JSON sidecars + manifest directory  ┘

BIDS JSON sidecars ──> deid_bids_sidecars.py (dry run by default)
```

## Repository Layout

```text
.
├── create_image03_files.sh
├── src/
│   ├── build_image03.py
│   └── deid_bids_sidecars.py
├── examples/
│   ├── config/example_config.json
│   └── input/
│       ├── bids/                 # BIDS-like folders and JSON sidecars
│       ├── manifests/            # example manifests
│       ├── participants.csv      # participant mapping table
│       ├── visits.csv            # session-date table
│       └── image03_template.csv  # minimal two-row template for tests/examples
└── tests/
```

## Requirements

- Python 3.10 or newer
- Bash, if using `create_image03_files.sh`

## Build an image03 CSV

The builder expects metadata tables (see input tables below) and a current [NDA template](https://nda.nih.gov/data-structure/image03).

### 1. Prepare Input Tables

`participants.csv` must contain:

| Column | Meaning |
|---|---|
| `source_subject_id` | BIDS participant label without the `sub-` prefix |
| `subjectkey` | NDA GUID/participant key for the participant |
| `sex` | Value mapped to the current NDA template's `sex` field |
| `date_of_birth` | Used only to calculate `interview_age`; never written to the output |
| `exclude` | Set to `true`, `yes`, or `1` to omit the participant |

`visits.csv` must contain:

| Column | Meaning |
|---|---|
| `source_subject_id` | BIDS participant label without the `sub-` prefix |
| `session_id` | BIDS session label without the `ses-` prefix |
| `interview_date` | Visit date; accepts `MM/DD/YYYY`, `MM/DD/YY`, or `YYYY-MM-DD` (also `MM-DD-YYYY` and `YYYY/MM/DD`) |

The BIDS directory should contain folders of the form `sub-<ID>/ses-<ID>/`. By default, the builder looks for a sidecar matching `*_T1w.json` within each session. Change this with `--sidecar-pattern` when appropriate.

Manifests should be named `sub-<ID>_ses-<ID>_manifest.json` and stored together in the directory passed to `--manifests`. Manifests can be generated using [nda_manifests.py](https://github.com/NDAR/manifest-data).

### 2. Supply Current NDA Template

Download the current `image03` submission template from the [NDA site](https://nda.nih.gov/data-structure/image03). The builder preserves the template's first two rows and fills fields by name, leaving other fields blank unless configured. The included example template has only a small subset of fields and is **not** a current NDA template.

### 3. Configure Constant and Sidecar-Derived Fields

Edit a copy of `examples/config/example_config.json` for the study and template you are authorized to work with. `constant_fields` sets fields that have the same value for every row. `sidecar_field_map` maps JSON sidecar keys to NDA column names.

Only include field mappings that are appropriate for the acquisition and confirmed against the current NDA data dictionary. This example maps `SoftwareVersions` and `DeviceSerialNumber`; it does not attempt to infer every image03 field from BIDS metadata.

### 4. Run the Builder

From the repository root:

```bash
./create_image03_files.sh \
  --bids-root examples/input/bids \
  --participants examples/input/participants.csv \
  --visits examples/input/visits.csv \
  --manifests examples/input/manifests \
  --template examples/input/image03_template.csv \
  [--config examples/config/example_config.json] \
  [--output /tmp/image_03.csv] \
  [--missing-report /tmp/missing_links.csv]
```

Or call Python directly:

```bash
python3 src/build_image03.py --help
```

The output CSV contains the original two template header rows followed by one row per eligible BIDS session. The `interview_age` value is calculated from date of birth and visit date, rounded to the nearest average Gregorian month (`365.25 / 12` days). The date of birth is not copied into the submission CSV. `--missing-report` is an optional argument to specify the location of an output file identifying issues such as a missing participant mapping, visit record, subjectkey/GUID, or manifest file. If this argument is not included, a missing_links.csv file will be written to the current working directory by default. Date and sidecar issues are printed as warnings rather than added to the CSV. The report does not currently list unused/orphaned rows in the participants or visits CSVs that do not correspond to a discovered BIDS session.

This builder does **not** generate manifest JSON files or validate their contents. It expects manifests to have been generated separately (e.g., using [nda_manifests.py](https://github.com/NDAR/manifest-data)).

## Review and Strip Identifying Information from Selected JSON Metadata Fields

The de-identification script is **dry-run by default**. It does not write changes unless `--write` is supplied.

Preview proposed changes:

```bash
python3 src/deid_bids_sidecars.py /path/to/a/working-copy-of-bids
```

Apply the configured changes to a working copy:

```bash
python3 src/deid_bids_sidecars.py /path/to/a/working-copy-of-bids --write
```

By default, the script removes these top-level JSON keys when present: `ProcedureStepDescription`, `InstitutionAddress`, `InstitutionalDepartmentName`, `PatientID`, `PatientName`, `AccessionNumber`, `ReferringPhysicianName`, and `OperatorsName`. If `InstitutionName` is present, the script replaces it with a site label inferred from the path using a configurable regular expression. If no site label is found, it removes `InstitutionName` rather than leaving the original value in place.

The default site pattern expects a path component containing `sub-` followed by the letter `M` and three digits (site key) and an optional alphanumeric suffix (e.g., `sub-M000xxxxx`, where `M000` is a site-specific identifier). Override it with `--site-regex` if your anonymized BIDS labels use another convention. The expression must include a named `site` capture group, for example:

```bash
python3 src/deid_bids_sidecars.py /path/to/working-copy \
  --site-regex 'sub-(?P<site>M\d{3})[A-Za-z0-9]*' --write
```

Additional top-level keys can be removed with repeated `--remove-field KEY` options. Run this only against a working copy and separately review filenames, directory labels, NIfTI/DICOM headers, other metadata files, dates, free text, and all applicable institutional requirements.

## Tests and Synthetic Example

Run the unit tests with:

```bash
python3 -m unittest discover -s tests -v
```

Run the example builder using the command in the previous section. All records and metadata in `examples/` are invented test fixtures. The example manifests contain placeholder checksums.

## NDA and BIDS References

- [NDA manifest data repository](https://github.com/NDAR/manifest-data) — explains the manifest data element and the JSON manifest format; supplies code to generate manifest files.
- [NDA `nda-tools` repository](https://github.com/NDAR/nda-tools) — installation, authentication, validation, and submission workflow. The `vtcmd` client is used for submissions that include manifest data elements.
- [NDA image03 data dictionary](https://nda.nih.gov/ndar_data_dictionary.html?short_name=image03) — current element definitions, requirements, and notes.
- [BIDS specification](https://bids-specification.readthedocs.io/en/stable/) — reference for the organization and naming of BIDS datasets and metadata.

For orientation, the NDAR manifest documentation shows the general `vtcmd` pattern for a submission that uses manifests:

```bash
vtcmd /path/to/image_03.csv \
  -m /path/to/manifests \
  -l /path/to/associated/files \
  -t "Submission title" \
  -d "Submission description" \
  -c COLLECTION_ID \
  -b
```

This is an example only. Confirm current syntax with `vtcmd -h` and the current NDA instructions. The official NDA documentation and validation tools are authoritative for submission requirements. This repository is an auxiliary metadata-preparation example, not a substitute for them.
