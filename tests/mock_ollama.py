"""Tiny fake Ollama server for tests: returns a fixed JSON 'message.content'."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def start(reply_json: dict):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.dumps({"message": {"content": json.dumps(reply_json)}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/api/chat"
