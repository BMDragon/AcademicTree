#!/usr/bin/env bash
# Serve the viewer at http://localhost:${1:-8000} (forward the port in VS Code Remote-SSH).
# Quiet: no per-request access log in the terminal.
cd "$(dirname "$0")/web" && exec python3 -c '
import functools, http.server, sys
port = int(sys.argv[1])
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory="."))
print("Academic Tree: http://localhost:%d  (Ctrl+C to stop)" % port, flush=True)
try:
    srv.serve_forever()
except KeyboardInterrupt:
    pass
' "${1:-8000}"
