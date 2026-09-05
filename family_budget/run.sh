#!/usr/bin/env bash
set -e

# If running as Home Assistant Add-on, read options from /data/options.json
if [ -f /data/options.json ]; then
    echo "Running as Home Assistant Add-on, loading configuration..."
    export TELEGRAM_BOT_TOKEN=$(python3 -c "import json; print(json.load(open('/data/options.json')).get('telegram_bot_token', ''))")
    export ALLOWED_USER_IDS=$(python3 -c "import json; print(json.load(open('/data/options.json')).get('allowed_user_ids', ''))")
    export OPENAI_API_KEY=$(python3 -c "import json; print(json.load(open('/data/options.json')).get('openai_api_key', ''))")
fi

echo "============================================"
echo "  Family Budget Tracker"
echo "  Dashboard: http://localhost:8000"
echo "============================================"

exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
