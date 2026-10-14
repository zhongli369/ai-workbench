"""Fleet endpoint mock (ops-owned, hash-pinned).

Serves the FLEET-OK banner on 127.0.0.1:19411 — one banner per connection,
then close. Runs forever; background it.
"""
import socketserver
import sys

BIND = ("127.0.0.1", 19411)
BANNER = b"FLEET-OK edge-02\n"


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.sendall(BANNER)
        except OSError:
            pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with _Server(BIND, _Handler) as srv:
        print(f"fleet mock listening on {BIND[0]}:{BIND[1]}", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            sys.exit(0)
