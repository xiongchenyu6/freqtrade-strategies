#!/usr/bin/env bash
# Execute SQL on Supabase via Management API.
#
# Usage:
#   ./scripts/supabase_sql.sh 'SELECT count(*) FROM dca_log'
#   ./scripts/supabase_sql.sh --file supabase/supabase_schema_dca.sql
#
# Requires SUPABASE_MGMT_TOKEN in secrets.env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_REF="${SUPABASE_PROJECT_REF:-}"
[[ -n "$PROJECT_REF" ]] || { echo "Set SUPABASE_PROJECT_REF env var (your Supabase project ref)"; exit 1; }

cd "$PROJECT_DIR"

if [[ "${1:-}" == "--file" ]]; then
    [[ -f "${2:-}" ]] || { echo "File not found: ${2:-}"; exit 1; }
    QUERY=$(cat "$2")
else
    QUERY="${1:-}"
fi

[[ -n "$QUERY" ]] || { echo "Usage: $0 '<sql>' | --file <path>"; exit 1; }

TOKEN=$(sops exec-env secrets.env 'echo "$SUPABASE_MGMT_TOKEN"')
[[ -n "$TOKEN" ]] || { echo "SUPABASE_MGMT_TOKEN missing in secrets.env"; exit 1; }

# JSON-escape the query
ESCAPED=$(python -c "import json,sys; print(json.dumps(sys.stdin.read()))" <<< "$QUERY")

curl -s -X POST "https://api.supabase.com/v1/projects/${PROJECT_REF}/database/query" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"query\": ${ESCAPED}}" \
    | python -c "import sys, json; d=json.load(sys.stdin); print(json.dumps(d, indent=2)) if isinstance(d, list) else print(d)"
