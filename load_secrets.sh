#!/usr/bin/env bash
# Source this file to load secrets into environment:
#   source load_secrets.sh
#
# Requires: sops, GPG key 3D7331009E93CC97A8CA809D03DFD2DEA7AF6693

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS=$(sops decrypt --output-type json "$SCRIPT_DIR/secrets.yaml" 2>/dev/null)

if [ $? -ne 0 ]; then
    echo "Failed to decrypt secrets. Check GPG key."
    return 1 2>/dev/null || exit 1
fi

export SUPABASE_URL=$(echo "$SECRETS" | python -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['supabase']['url'])")
export SUPABASE_KEY=$(echo "$SECRETS" | python -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['supabase']['publishable_key'])")
export ZYTE_API_KEY=$(echo "$SECRETS" | python -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['zyte']['api_key'])")
export DEEPNOTE_API_KEY=$(echo "$SECRETS" | python -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['deepnote']['api_key'])")
export DEEPNOTE_PROJECT_ID=$(echo "$SECRETS" | python -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['deepnote']['project_id'])")
export DEEPNOTE_NOTEBOOK_ID=$(echo "$SECRETS" | python -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['deepnote']['notebook_id'])")
export TELEGRAM_BOT_TOKEN=$(echo "$SECRETS" | python -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['telegram']['bot_token'])")
export TELEGRAM_CHAT_ID=$(echo "$SECRETS" | python -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['telegram']['chat_id'])")

echo "Secrets loaded: SUPABASE_URL, SUPABASE_KEY, ZYTE_API_KEY, DEEPNOTE_*, TELEGRAM_*"
