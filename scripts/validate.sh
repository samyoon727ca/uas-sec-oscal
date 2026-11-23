#!/usr/bin/env bash
# Validate OSCAL files with the pinned oscal-cli (see scripts/install-oscal-cli.sh).
#
# Usage: scripts/validate.sh FILE...
#
# The OSCAL model of each file is detected from its root (a JSON key, an XML element or
# a top-level YAML key) and the file is passed to `oscal-cli <model> validate`. The script
# exits non-zero if any file fails validation or its model cannot be detected.
# Set OSCAL_CLI to use an oscal-cli other than .tools/oscal-cli/bin/oscal-cli, either as a
# path or as a command name on PATH. JSON files are read with Python (python3 or python).
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
oscal_cli="${OSCAL_CLI:-${root}/.tools/oscal-cli/bin/oscal-cli}"

if [[ $# -eq 0 ]]; then
  echo "usage: $0 FILE..." >&2
  exit 2
fi
# Resolve a bare command name on PATH as well as a path.
if ! resolved="$(command -v -- "${oscal_cli}")"; then
  echo "error: ${oscal_cli} not found; run scripts/install-oscal-cli.sh first" >&2
  exit 2
fi
oscal_cli="${resolved}"
python=""
for candidate in python3 python; do
  if "${candidate}" -c '' >/dev/null 2>&1; then
    python="${candidate}"
    break
  fi
done

roots='catalog|profile|component-definition|system-security-plan|assessment-plan|assessment-results|plan-of-action-and-milestones'

# Print the oscal-cli command for the model of file $1, or nothing if it is not detected.
detect_model() {
  local file="$1" root_name=""
  case "${file}" in
    *.json)
      if [[ -n "${python}" ]]; then
        # Only top-level keys count; a nested key named like a root (or "$schema") does not.
        root_name="$("${python}" -c 'import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
print("\n".join(doc) if isinstance(doc, dict) else "")' "${file}" 2>/dev/null |
          tr -d '\r' | grep -xE "${roots}" | head -n1)"
      fi
      ;;
    *.xml) root_name="$(grep -oE -m1 "<(${roots})([[:space:]>/]|$)" -- "${file}" | grep -oE "${roots}" | head -n1)" ;;
    *.yaml | *.yml) root_name="$(grep -oE -m1 "^(${roots}):" -- "${file}" | grep -oE "${roots}" | head -n1)" ;;
  esac
  case "${root_name}" in
    catalog) echo catalog ;;
    profile) echo profile ;;
    component-definition) echo component-definition ;;
    system-security-plan) echo ssp ;;
    assessment-plan) echo ap ;;
    assessment-results) echo ar ;;
    plan-of-action-and-milestones) echo poam ;;
  esac
}

failed=0
for file in "$@"; do
  if [[ ! -f "${file}" ]]; then
    echo "FAIL ${file}: no such file" >&2
    failed=1
    continue
  fi
  model="$(detect_model "${file}")"
  if [[ -z "${model}" ]]; then
    echo "FAIL ${file}: cannot detect the OSCAL model (expected .json, .xml, .yaml or .yml with an OSCAL root)" >&2
    failed=1
    continue
  fi
  echo "==> oscal-cli ${model} validate ${file}"
  if "${oscal_cli}" "${model}" validate "${file}"; then
    echo "PASS ${file}"
  else
    echo "FAIL ${file}" >&2
    failed=1
  fi
done

exit "${failed}"
