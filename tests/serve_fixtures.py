from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def create_server() -> ThreadingHTTPServer:
    handler = partial(SimpleHTTPRequestHandler, directory=str(FIXTURES_DIR))
    return ThreadingHTTPServer(("127.0.0.1", 0), handler)


def main() -> None:
    with create_server() as server:
        host, port = server.server_address
        print(f"Fixture server: http://{host}:{port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Fixture server stopped.", flush=True)


if __name__ == "__main__":
    main()
