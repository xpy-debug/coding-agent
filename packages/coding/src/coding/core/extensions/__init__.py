"""Extension system for plugin-based customization of the coding agent.

Provides discovery, loading, and execution of extensions that can hook
into agent events, register custom tools, commands, and modify behavior.
"""

from coding.core.extensions.loader import (
    discover_and_load_extensions,
    discover_extensions_in_dir,
    load_extension_from_factory,
    load_extensions,
)
from coding.core.extensions.runner import ExtensionRunner
from coding.core.extensions.types import (
    Extension,
    ExtensionAPI,
    ExtensionContext,
    ExtensionError,
    ExtensionEvent,
    ExtensionFactory,
    RegisteredCommand,
    RegisteredTool,
    ToolDefinition,
)
from coding.core.extensions.wrapper import (
    wrap_registered_tool,
    wrap_registered_tools,
    wrap_tool_with_extensions,
    wrap_tools_with_extensions,
)

__all__ = [
    "Extension",
    "ExtensionAPI",
    "ExtensionContext",
    "ExtensionError",
    "ExtensionEvent",
    "ExtensionFactory",
    "ExtensionRunner",
    "RegisteredCommand",
    "RegisteredTool",
    "ToolDefinition",
    "discover_and_load_extensions",
    "discover_extensions_in_dir",
    "load_extension_from_factory",
    "load_extensions",
    "wrap_registered_tool",
    "wrap_registered_tools",
    "wrap_tool_with_extensions",
    "wrap_tools_with_extensions",
]
