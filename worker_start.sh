#!/usr/bin/env bash
set -e

# Dummy HTTP server on $PORT so Render considers this service "healthy".
# Without it, Render kills web services that don't bind to $PORT.
python -c "
import os, threading, http.server

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'worker ok')
    def log_message(self, *args):
        pass  # silence logs

port = int(os.environ.get('PORT', 10000))
server = http.server.HTTPServer(('0.0.0.0', port), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print(f'Health server listening on :{port}')
" &

# Give the health server a moment to bind
sleep 1

# Start Celery worker + beat in one process
celery -A config worker -l info --beat
