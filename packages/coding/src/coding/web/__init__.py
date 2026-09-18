"""coding-web: Web UI for AI chat with FastAPI and WebSockets."""

from coding.web.app import create_app
from coding.web.config import Config

__all__ = ["Config", "create_app"]
