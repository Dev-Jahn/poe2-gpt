"""Run with the installed virtualenv Python to bind this local plugin to it."""
import importlib.util
import json
import sys
from pathlib import Path

if importlib.util.find_spec("poe2_companion") is None:
    raise SystemExit("Install this project with this Python interpreter first: python -m pip install .")
root = Path(__file__).resolve().parents[1]
config = {"mcpServers": {"poe2-gpt": {
    "command": sys.executable,
    "args": ["-m", "poe2_companion.server", "--transport", "stdio"],
}}}
(root / ".mcp.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(config, ensure_ascii=False, indent=2))
print("\nDesktop MCP: use the command and arguments above. Web ChatGPT needs remote HTTP or Secure MCP Tunnel.")
