"""App data folder: %APPDATA%/HolographicHullabaloo on Windows.
Override with the HH_DATA_DIR environment variable (tests, portable mode)."""
import os, sys

APP = "HolographicHullabaloo"


def data_dir():
    d = os.environ.get("HH_DATA_DIR")
    if not d:
        if sys.platform == "win32":
            d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP)
        else:
            d = os.path.join(os.path.expanduser("~/.local/share"), APP)
    for sub in ("", "models", "logs", "personas"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def p(*parts):
    return os.path.join(data_dir(), *parts)
