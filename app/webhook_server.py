"""Part 4 student implementation."""

import json

import logging

import os

from concurrent.futures import ThreadPoolExecutor

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from tempfile import TemporaryDirectory

from app.integration import process_request

from app.webex_client import WEBEX_API_BASE, WebexClient

logger = logging.getLogger(__name__)

MAX_BODY_LENGTH = 1_000_000

class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def _message_id(self, event):
        if not isinstance(event, dict):
            return None
        if event.get("resource") != "messages" or event.get("event") != "created":
            return None
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        # Skip our own replies before calling the Webex API.
        if data.get("personId") == self.bot_person_id:
            return None
        message_id = data.get("id")
        if not isinstance(message_id, str) or not message_id:
            return None
        return message_id

    def _process(self, message):
        mentioned_people = message.get("mentionedPeople") or []
        files = message.get("files") or []

        if len(files) > 1:
            return {"status": "error", "result": "multiple_attachments"}

        try:
            if not files:
                return self.processor(mentioned_people, None, self.bot_person_id)

            content = self.client.download_file(files[0])
            with TemporaryDirectory() as directory:
                path = Path(directory) / "request.yaml"
                path.write_bytes(content)
                return self.processor(mentioned_people, path, self.bot_person_id)
        except Exception:
            logger.exception("request processing failed")
            return {"status": "error", "result": "backend_failed"}

    def handle_event(self, event):
        message_id = self._message_id(event)
        if message_id is None:
            return None

        message = self.client.get_message(message_id)
        if not isinstance(message, dict):
            return None
        # Second loop guard: the fetched author may be the bot itself.
        if message.get("personId") == self.bot_person_id:
            return None

        room_id = message.get("roomId")
        if not room_id:
            return None

        result = self._process(message)
        self.client.send_message(room_id, json.dumps(result))
        return result

def make_http_handler(submit_event):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code, body):
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/health":
                self._reply(200, {"status": "ok", "result": "healthy"})
            else:
                self._reply(404, {"status": "error", "result": "not_found"})

        def do_POST(self):
            if self.path != "/webhook":
                self._reply(404, {"status": "error", "result": "not_found"})
                return

            invalid = {"status": "error", "result": "invalid_event"}
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._reply(400, invalid)
                return
            if not 1 <= length <= MAX_BODY_LENGTH:
                self._reply(400, invalid)
                return

            try:
                event = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                self._reply(400, invalid)
                return
            if not isinstance(event, dict):
                self._reply(400, invalid)
                return

            submit_event(event)
            self._reply(200, {"status": "ok", "result": "accepted"})

        def log_message(self, format, *args):
            logger.info("%s - %s", self.address_string(), format % args)

    return Handler

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    client = WebexClient()
    bot_person_id = client.get_me()["id"]
    handler = WebexEventHandler(client, bot_person_id)

    # One worker: router changes are processed sequentially.
    executor = ThreadPoolExecutor(max_workers=1)

    def run(event):
        try:
            handler.handle_event(event)
        except Exception:
            logger.exception("event handling failed")

    def submit_event(event):
        executor.submit(run, event)

    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), make_http_handler(submit_event))
    logger.info("webhook listening on %s:%s (Webex API %s)", host, port, WEBEX_API_BASE)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        executor.shutdown(wait=False)

if __name__ == "__main__":
    main()
