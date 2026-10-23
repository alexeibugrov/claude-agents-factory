#!/usr/bin/env bash
# Run scripts/try_scrape.py in the agent's own image on a Docker-only host; usage: README § Develop.
# --out paths under /out land in scripts/out/ (gitignored).
set -euo pipefail

agent_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="upwork-scout:try-scrape"
out_dir="${agent_dir}/scripts/out"
mkdir -p "${out_dir}"

if [[ -n "${APIFY_TOKEN:-}" ]]; then
  token_args=(-e APIFY_TOKEN)
elif [[ -n "${APIFY_ENV_FILE:-}" ]]; then
  token_args=(--env-file "${APIFY_ENV_FILE}")
else
  echo "Set APIFY_TOKEN, or APIFY_ENV_FILE to a file containing APIFY_TOKEN=..." >&2
  exit 1
fi

docker build -q -t "${image}" "${agent_dir}" >/dev/null

docker run --rm \
  "${token_args[@]}" \
  -e SEARCH_URL \
  --user "$(id -u):$(id -g)" \
  -v "${agent_dir}/scripts:/app/scripts:ro" \
  -v "${agent_dir}/agent_config.yaml:/app/agent_config.yaml:ro" \
  -v "${out_dir}:/out" \
  "${image}" python -u scripts/try_scrape.py "$@"
