"""Entry point for coding-web CLI."""

from __future__ import annotations

import argparse
import logging


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    from coding.web.config import DEFAULT_HOST

    parser = argparse.ArgumentParser(description="coding-web: AI Chat Web Interface")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST}, local access only)",
    )
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    parser.add_argument("--db", default=None, help="SQLite database path")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    return parser


def main() -> None:
    args = build_parser().parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from coding.web.config import Config

    config = Config(host=args.host, port=args.port)
    if args.db:
        config.db_path = args.db

    from coding.web.app import create_app

    app = create_app(config)

    import uvicorn

    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
