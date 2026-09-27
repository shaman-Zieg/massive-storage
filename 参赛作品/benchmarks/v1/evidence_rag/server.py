"""Local single-request HTTP service, compatible with the supplied benchmark."""
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from .agent import Agent
from .models import ModelError


def validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"question"}:
        raise ValueError("Only the question field is accepted")
    value = payload["question"]
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise ValueError("Invalid question")
    return value


def make_handler(agent):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(300)

        def respond(self, status, payload):
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.respond(200 if self.path=="/health" else 404,
                         {"status": "ready", "mode": "competition", "models_probed": False}
                         if self.path=="/health" else {"error": "not found"})

        def do_POST(self):
            if self.path != "/query":
                self.respond(404, {"error": "not found"}); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(length))
                question = validate_payload(payload)
            except (ValueError, UnicodeError):
                self.respond(400, {"error": "Expected JSON containing only a valid question"}); return
            start = time.perf_counter()
            try:
                self.respond(200, agent.answer(question))
            except ModelError as exc:
                self.respond(503, {"error": str(exc), "query_time_s": time.perf_counter()-start})
            except Exception:
                self.respond(500, {"error": "Internal error; inspect local service logs"})
                import traceback
                traceback.print_exc()

        def log_message(self, fmt, *args):
            # Only request status is logged; no question text, credentials or source images.
            print(fmt % args, flush=True)
    return Handler


def serve(config, host="127.0.0.1", port=8080):
    agent = Agent(config)
    with HTTPServer((host, port), make_handler(agent)) as server:
        print(f"Listening on http://{host}:{port}/query", flush=True)
        server.serve_forever()
