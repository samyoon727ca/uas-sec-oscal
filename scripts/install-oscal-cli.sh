#!/usr/bin/env bash
# Install a pinned NIST oscal-cli release into .tools/oscal-cli/.
#
# Pins:
#   oscal-cli   1.0.3  (Maven Central gov.nist.secauto.oscal.tools.oscal-cli:cli-core)
#   OSCAL model 1.1.2  (the schemas bundled in liboscal-java 3.0.3, which oscal-cli 1.0.3 ships)
#
# The archive is checked against the SHA-256 below before it is unpacked. To move the
# pin, change both values together and update the README.
#
# Requires: bash, curl, unzip, sha256sum or shasum. Running oscal-cli needs Java 11+.
set -euo pipefail

OSCAL_CLI_VERSION="1.0.3"
OSCAL_CLI_SHA256="c90166b6f94a8b32a4c0012bb3f3d32dfa54b950aed31ac1a4902ce75fc6a57e"
OSCAL_CLI_URL="https://repo1.maven.org/maven2/gov/nist/secauto/oscal/tools/oscal-cli/cli-core/${OSCAL_CLI_VERSION}/cli-core-${OSCAL_CLI_VERSION}-oscal-cli.zip"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${root}/.tools/oscal-cli"
stamp="${dest}/.pinned"
want="${OSCAL_CLI_VERSION} ${OSCAL_CLI_SHA256}"

if [[ -f "${stamp}" && "$(cat "${stamp}")" == "${want}" && -f "${dest}/bin/oscal-cli" ]]; then
  echo "oscal-cli ${OSCAL_CLI_VERSION} already installed in ${dest}"
  exit 0
fi

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

mkdir -p "${root}/.tools"
tmp="$(mktemp -d "${root}/.tools/tmp.XXXXXX")"
trap 'rm -rf "${tmp}"' EXIT

echo "Downloading ${OSCAL_CLI_URL}"
# Maven Central rate-limits (HTTP 429) shared CI runners; back off long enough to ride it out.
curl -fsSL --retry 6 --retry-delay 15 -o "${tmp}/oscal-cli.zip" "${OSCAL_CLI_URL}"

actual="$(sha256 "${tmp}/oscal-cli.zip")"
if [[ "${actual}" != "${OSCAL_CLI_SHA256}" ]]; then
  echo "error: SHA-256 mismatch for oscal-cli ${OSCAL_CLI_VERSION}" >&2
  echo "  expected ${OSCAL_CLI_SHA256}" >&2
  echo "  actual   ${actual}" >&2
  exit 1
fi
echo "SHA-256 verified: ${actual}"

unzip -q "${tmp}/oscal-cli.zip" -d "${tmp}/unpacked"
if [[ ! -f "${tmp}/unpacked/bin/oscal-cli" ]]; then
  echo "error: archive has no bin/oscal-cli" >&2
  exit 1
fi
chmod +x "${tmp}/unpacked/bin/oscal-cli"

rm -rf "${dest}"
mv "${tmp}/unpacked" "${dest}"
printf '%s\n' "${want}" > "${stamp}"
echo "Installed oscal-cli ${OSCAL_CLI_VERSION} in ${dest}"
