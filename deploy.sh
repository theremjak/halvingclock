#!/usr/bin/env bash
# Local build + deploy (the daily GitHub Action does the same thing in the cloud).
#   ./deploy.sh            fetch fresh data, build, deploy
#   ./deploy.sh --offline  rebuild from cache/ and deploy
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$PATH"
PY="${PY:-../.venv/bin/python}"
"$PY" build.py "$@"
npx wrangler@latest deploy
