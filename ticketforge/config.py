"""Load and save the user's TicketForge credentials."""

import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".ticketforge.json"


def save_config(username, password):
    CONFIG_PATH.write_text(json.dumps({"username": username, "password": password}))
    CONFIG_PATH.chmod(0o600)  # owner-only on Linux/macOS


def load_config():
    """Return (username, password), or None if not configured.

    Environment variables override the saved file.
    """
    config = {}
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())

    username = os.environ.get("TICKETFORGE_USERNAME", config.get("username"))
    password = os.environ.get("TICKETFORGE_PASSWORD", config.get("password"))
    if not username or not password:
        return None
    return username, password
