"""Configuration applicative : charge config.json et expose APP_CONFIG."""
import json
import os

from core.env import PROJECT_DIR

_CONFIG_FILE = os.path.join(PROJECT_DIR, "config.json")

with open(_CONFIG_FILE) as _f:
    APP_CONFIG: dict = json.load(_f)
