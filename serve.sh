#!/usr/bin/env bash
# Serve the viewer at http://localhost:${1:-8000} (forward the port in VS Code Remote-SSH).
# Quiet (no per-request log) and gzip-compressed (the data files shrink ~8x,
# which matters over an SSH port-forward).
cd "$(dirname "$0")/web" && exec python3 -c '
import functools, gzip, http.server, os, sys
port = int(sys.argv[1])
_cache = {}

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_head(self):
        path = self.translate_path(self.path)
        gz_ok = "gzip" in self.headers.get("Accept-Encoding", "")
        if not (gz_ok and os.path.isfile(path) and path.endswith((".json", ".js", ".css", ".html", ".svg"))):
            return super().send_head()
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
        body = _cache.get(key)
        if body is None:
            with open(path, "rb") as f:
                body = gzip.compress(f.read(), 6)
            _cache.clear() if len(_cache) > 50 else None
            _cache[key] = body
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        import io
        return io.BytesIO(body)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory="."))
print("Academic Tree: http://localhost:%d  (Ctrl+C to stop)" % port, flush=True)
try:
    srv.serve_forever()
except KeyboardInterrupt:
    pass
' "${1:-8000}"
