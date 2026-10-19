"""Preview the built site locally.

Usage::

    python -m hawk.site.serve              # build, then serve on http://localhost:8000
    python -m hawk.site.serve --no-build --port 8080
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
from pathlib import Path

from hawk.site.build import OUT_DIR
from hawk.site.build import main as build_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dir", type=Path, default=OUT_DIR)
    parser.add_argument("--no-build", action="store_true", help="serve the existing build")
    args = parser.parse_args(argv)
    if not args.no_build:
        build_main(["--out", str(args.dir)])
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(args.dir))
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"Serving {args.dir} at http://localhost:{args.port}/ (Ctrl+C to stop)")
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
