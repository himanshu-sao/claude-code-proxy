#!/usr/bin/env bash
# Restart the Claude Code Proxy server by stopping and then starting it.

# Change to the repository root
cd "$(dirname "$0")" || exit 1

# Stop the proxy if it's running
if [[ -x ./stop.sh ]]; then
  ./stop.sh
fi

# Start the proxy
if [[ -x ./start.sh ]]; then
  ./start.sh
else
  echo "Error: start.sh not found or not executable."
fi
