#!/usr/bin/env bash
# Start the Claude Code Proxy server using uv.
# Stores the PID in .proxy.pid for later stop/restart.

# Change to the repository root (where this script lives)
cd "$(dirname "$0")"

# Load PORT from .env if available, otherwise default to 8082
if [ -f .env ]; then
    PORT=$(grep '^PORT=' .env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    ENV_ANTHROPIC_KEY=$(grep '^ANTHROPIC_API_KEY=' .env | cut -d'=' -f2 | tr -d '"' | tr -d "'" | tr -d ' ')
    if [ -z "$ENV_ANTHROPIC_KEY" ]; then
        unset ANTHROPIC_API_KEY
    fi
fi
PORT=${PORT:-8082}

# Check if any process is using the port
PORT_PID=$(lsof -t -i :$PORT)
if [ -n "$PORT_PID" ]; then
    # Get the name of the process using the port
    APP_NAME=$(ps -p $PORT_PID -o comm= | xargs basename)
    echo "⚠️ Port $PORT is already in use by '$APP_NAME' (PID $PORT_PID)."
    read -p "Do you want to kill this process and start fresh? (y/N): " confirm
    if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
        echo "Clearing port $PORT..."
        kill -9 $PORT_PID 2>/dev/null
        sleep 1
    else
        echo "Start aborted by user."
        exit 1
    fi
fi

# Check if proxy is already running via PID file
if [ -f .proxy.pid ]; then
    PID=$(cat .proxy.pid)
    if ps -p $PID > /dev/null; then
        echo "Claude Code Proxy is already running (PID $PID). Stopping it..."
        kill $PID
        sleep 1
    fi
fi

# Ensure a logs directory exists
mkdir -p logs
# Launch the proxy in the background, capturing stdout and stderr to a log file
log_file="logs/proxy_$(date +'%Y%m%d_%H%M%S').log"

uv run start_proxy.py > "$log_file" 2>&1 &
PID=$!

echo $PID > .proxy.pid
echo "Claude Code Proxy started (PID $PID) on port $PORT. Logs: $log_file"
