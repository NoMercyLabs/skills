"""HTTP entry point: routing, JSON bodies, auth header handling and CORS."""
import json
import logging
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from app import auth, config, db, routes, validation

log = logging.getLogger("server")


def compile_routes(table):
    compiled = []
    for method, pattern, handler in table:
        regex = re.compile("^" + re.sub(r"\{id\}", r"(\\d+)", pattern) + "$")
        compiled.append((method, regex, handler))
    return compiled


COMPILED = compile_routes(routes.ROUTES)


class Request:
    def __init__(self, handler, conn, params, user):
        self._handler = handler
        self.conn = conn
        self.params = params
        self.user = user

    def json(self):
        length = int(self._handler.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise routes.HttpError(413, "body too large")
        raw = self._handler.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except ValueError:
            raise routes.HttpError(400, "body is not valid JSON")
        if not isinstance(data, dict):
            raise routes.HttpError(400, "body must be an object")
        return data

    def body_bytes(self, limit):
        length = int(self._handler.headers.get("Content-Length") or 0)
        if length > limit:
            raise routes.HttpError(413, "upload too large")
        return self._handler.rfile.read(length)

    def file_response(self, path, kind="application/octet-stream"):
        with open(path, "rb") as handle:
            return {"__file__": handle.read(), "__type__": kind}


class Handler(BaseHTTPRequestHandler):
    server_version = "taskboard"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin and origin in config.ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Headers", "Authorization, Content-Type"
            )
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS"
            )

    def _send(self, status, body):
        if isinstance(body, dict) and "__file__" in body:
            payload, kind = body["__file__"], body["__type__"]
        else:
            payload = json.dumps(body).encode("utf-8")
            kind = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _authenticate(self):
        header = self.headers.get("Authorization")
        if not header:
            return None
        try:
            return auth.user_from_header(header)
        except auth.AuthError as error:
            raise routes.HttpError(401, str(error))

    def _dispatch(self, method):
        parts = urlsplit(self.path)
        params = {key: values[0] for key, values in parse_qs(parts.query).items()}
        conn = db.connect()
        try:
            for route_method, regex, handler in COMPILED:
                found = regex.match(parts.path)
                if route_method != method or not found:
                    continue
                req = Request(self, conn, params, self._authenticate())
                args = [int(value) for value in found.groups()]
                status, body = handler(req, *args)
                self._send(status, body)
                return
            self._send(404, {"error": "no such route"})
        except routes.HttpError as error:
            self._send(error.status, {"error": error.message})
        except validation.ValidationError as error:
            self._send(422, {"error": error.as_dict()})
        except Exception:
            log.exception("unhandled error for %s %s", method, self.path)
            self._send(500, {"error": "internal error"})
        finally:
            conn.close()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
    conn = db.connect()
    db.init_schema(conn)
    auth.ensure_admin(conn, db)
    conn.close()
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    log.info("listening on %s:%s", config.HOST, config.PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
