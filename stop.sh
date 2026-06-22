#!/usr/bin/env bash
# Stop the Claude Code Proxy server using the PID stored by start.sh.

# Change to the repository root
cd "$(dirname "$0")" || exit 1

PID_FILE=".proxy.pid"
if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Claude Code Proxy stopped (PID $PID)." >> logs/proxy_$(date +'%Y%m%d_%H%M%S').log
    rm -f "$PID_FILE"
  else
    echo "Process $PID not running; removing stale PID file."
    rm -f "$PID_FILE"
  fi
else
  echo "No PID file found. Is the proxy running?"
fi
