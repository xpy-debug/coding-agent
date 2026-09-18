"""Configuration for the web UI server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# The UI exposes full filesystem access through the coding tools, so it is
# local-only by design: binding to 0.0.0.0 would offer that to the whole
# network. Pass --host to override deliberately.
DEFAULT_HOST = "127.0.0.1"


@dataclass
class Config:
    """Server configuration."""

    host: str = DEFAULT_HOST
    port: int = 8000
    db_path: str = field(default_factory=lambda: str(Path.home() / ".coding" / "web-ui.db"))
    static_dir: str = field(default_factory=lambda: str(Path(__file__).parent / "static"))
    # Default working directory for the coding tools. Can be changed at
    # runtime from the UI; the active value is persisted in the database.
    workspace: str = field(default_factory=os.getcwd)
    # Directory used to discover custom model definitions (models.json).
    agent_dir: str = field(default_factory=lambda: str(Path.home() / ".coding"))
