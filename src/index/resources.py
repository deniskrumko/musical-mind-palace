"""Хранит общие константы и типы модулей пакета index."""

from pathlib import Path
from typing import Literal

INDEX_FILENAME = "INDEX.md"
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
TAG_CONFIG_PATH = CONFIG_DIR / "tags.toml"
ALBUM_CONFIG_PATH = CONFIG_DIR / "albums.toml"
TagType = Literal[
    "string",
    "text",
    "list",
    "single_choice",
    "multi_choice",
    "album_selector",
    "star_rating",
    "bool",
]
CHOICE_TYPES = {"single_choice", "multi_choice"}
LIST_TYPES = {"list", "multi_choice", "album_selector"}
