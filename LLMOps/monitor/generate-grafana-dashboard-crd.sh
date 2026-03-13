#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARDS_DIR="${SCRIPT_DIR}/grafana-dashboards"
OUTPUT_DIR="${SCRIPT_DIR}/grafana-dashboards-crd"
TEMPLATE_FILE="${OUTPUT_DIR}/grafana-dashboard-crd-tmpl.yaml"

if [[ ! -f "${TEMPLATE_FILE}" ]]; then
  echo "Error: template not found: ${TEMPLATE_FILE}" >&2
  exit 1
fi

if [[ ! -d "${DASHBOARDS_DIR}" ]]; then
  echo "Error: dashboards directory not found: ${DASHBOARDS_DIR}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

shopt -s nullglob
json_files=("${DASHBOARDS_DIR}"/*.json)

if (( ${#json_files[@]} == 0 )); then
  echo "No .json files found in ${DASHBOARDS_DIR}"
  exit 0
fi

for json_file in "${json_files[@]}"; do
  file_name="$(basename "${json_file}")"
  file_stem="${file_name%.json}"
  output_file="${OUTPUT_DIR}/${file_stem}.yaml"

  # Kubernetes metadata.name: lowercase alphanumerics and '-', max length 63.
  metadata_name="$(echo "${file_stem}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//; s/-{2,}/-/g' \
    | cut -c1-63)"

  if [[ -z "${metadata_name}" ]]; then
    echo "Skip ${file_name}: unable to build valid metadata.name" >&2
    continue
  fi

  awk '/^[[:space:]]*json:[[:space:]]*\|[[:space:]]*$/ { print; exit } { print }' "${TEMPLATE_FILE}" \
    | sed -E "s/^([[:space:]]*name:[[:space:]]*).*/\\1${metadata_name}/" > "${output_file}"

  sed 's/^/    /' "${json_file}" >> "${output_file}"
  echo "Generated: ${output_file}"
done
