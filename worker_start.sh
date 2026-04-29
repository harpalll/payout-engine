#!/usr/bin/env bash
set -e

# Start Celery worker + beat in background
celery -A config worker -l info --beat --concurrency=2 &

# Health server in foreground — Render needs this to detect the port
python -c "
import os, http.server

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'worker ok')
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass

port = int(os.environ.get('PORT', 10000))
print(f'Health server listening on :{port}')
http.server.HTTPServer(('0.0.0.0', port), Handler).serve_forever()
"
