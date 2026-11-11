"""Search the LGD hierarchy and serve an interactive graph of it.

Run from the repo root or from LGD/:

    python LGD/lgd_explorer.py

Then open the printed URL. Pass a query to print matches in the terminal
instead of starting the page:

    python LGD/lgd_explorer.py "Badar Pur Kdhar"
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lgd_directory import Directory


def print_search(directory: Directory, query: str) -> None:
    result = directory.search(query)
    if not result["matches"]:
        print(f"No match for {query!r}.")
        return
    print(f"{len(result['matches'])} match(es) by {result['kind']}:")
    for match in result["matches"]:
        print(f"{match['entity_type']}: {match['name_english']} → {match['lgd_code']}")
        if match.get("hierarchy"):
            print(f"  hierarchy: {match['hierarchy']}")
        print()


def serve(directory: Directory, port: int) -> None:
    html_path = Path(__file__).resolve().with_name("lgd_graph.html")
    html = html_path.read_bytes()
    graph = json.dumps(directory.graph_payload(), ensure_ascii=False).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html"}:
                self._send(html, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/graph":
                self._send(graph, "application/json; charset=utf-8")
                return
            if parsed.path == "/api/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                body = json.dumps(directory.search(query), ensure_ascii=False).encode("utf-8")
                self._send(body, "application/json; charset=utf-8")
                return
            self.send_error(404)

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            if args and str(args[1]).startswith("404"):
                super().log_message(fmt, *args)

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Indexed {len(directory.entities)} entities from {directory.source}")
    print(f"Graph page: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the LGD hierarchy or open its graph.")
    parser.add_argument("query", nargs="*", help="Print matches for this text and exit.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    directory = Directory.load()    
    if args.query:
        print_search(directory, " ".join(args.query))
        return
    serve(directory, args.port)


if __name__ == "__main__":
    main()
