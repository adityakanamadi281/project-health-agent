set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not on PATH — see https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv sync --frozen

if [[ "${1:-}" == "--monthly" ]]; then
  uv run project-health run-monthly
else
  uv run project-health run-weekly
fi


