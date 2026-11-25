#!/usr/bin/env bash
# Serve the viewer at http://localhost:${1:-8000}  (forward the port in VS Code Remote-SSH)
cd "$(dirname "$0")/web" && exec python3 -m http.server "${1:-8000}" --bind 127.0.0.1
