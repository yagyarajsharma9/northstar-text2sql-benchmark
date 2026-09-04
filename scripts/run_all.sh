#!/usr/bin/env bash
# NorthStar Chat - one-shot setup and run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_SEED=0
SKIP_INGEST=0
PORT=8000
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-seed)   SKIP_SEED=1; shift ;;
        --skip-ingest) SKIP_INGEST=1; shift ;;
        --port)        PORT="$2"; shift 2 ;;
        *)             shift ;;
    esac
done

echo "[1/4] Installing requirements..."
pip install -r requirements.txt --quiet

if [[ $SKIP_SEED -eq 0 ]]; then
    echo "[2/4] Seeding database..."
    python database/seed_data.py
else
    echo "[2/4] Skipping seed"
fi

if [[ $SKIP_INGEST -eq 0 ]]; then
    echo "[3/4] Ingesting documents..."
    python database/ingest_documents.py
else
    echo "[3/4] Skipping ingest"
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "WARN: ANTHROPIC_API_KEY not set; running in offline mode."
fi

echo "[4/4] Starting server on http://localhost:$PORT ..."
python -m uvicorn winning_architecture.server:app --port "$PORT"
