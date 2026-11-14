#!/usr/bin/env bash
# Convenience entry point for the Python image03 builder.
# Usage and required arguments are documented by: ./create_image03_files.sh --help
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/src/build_image03.py" "$@"
