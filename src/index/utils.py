"""Общие функции разбора индексов и поиска музыкальных директорий."""

import os
import re
from collections.abc import Iterable
from pathlib import Path

from core.logicx import is_directory

from .resources import INDEX_FILENAME


def trim_trailing_blank_lines(value: str) -> str:
    """Удаляет пустые строки только в конце многострочного значения."""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def parse_list_value(name: str, text: str) -> list[str]:
    """Разбирает список, игнорируя пустые строки и проверяя маркеры элементов."""
    value = trim_trailing_blank_lines(text)
    items: list[str] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        if not line.startswith("- "):
            raise ValueError(f"Строка списка тега {name!r} должна начинаться с '- '")
        item = line[2:].strip()
        if not item:
            raise ValueError(f"Значения списка тега {name!r} не должны быть пустыми")
        items.append(item)
    if not items:
        raise ValueError(f"Значение тега {name!r} не должно быть пустым")
    return items


def parse_star_rating(name: str, text: str) -> int:
    """Разбирает целочисленный рейтинг тега из Markdown."""
    value = trim_trailing_blank_lines(text).strip()
    if not re.fullmatch(r"\d+", value):
        raise ValueError(f"Значение рейтинга {name!r} должно быть целым числом от 1 до 10")
    return int(value)


def parse_bool_value(name: str, text: str) -> bool:
    """Разбирает логическое значение тега из Markdown."""
    value = trim_trailing_blank_lines(text).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"Значение тега {name!r} должно быть true или false")
    return value == "true"


def raise_walk_error(error: OSError) -> None:
    """Передаёт ошибку чтения каталога вызывающему коду."""
    raise error


def get_music_dirs(index_dir: Path, exclude_dirs: Iterable[Path] = ()) -> list[Path]:
    """Находит папки с INDEX.md, исключая ссылки, проекты и вложения песен."""
    index_dir = index_dir.expanduser()
    if not is_directory(index_dir):
        raise ValueError(f"INDEX_DIR не является обычной директорией: {index_dir}")
    excluded = [path.expanduser().resolve() for path in exclude_dirs]
    if any(index_dir.resolve().is_relative_to(path) for path in excluded):
        return []
    found: list[Path] = []
    for current, directories, files in os.walk(index_dir, onerror=raise_walk_error):
        folder = Path(current)
        index = folder / INDEX_FILENAME
        if INDEX_FILENAME in files and not index.is_symlink() and index.is_file():
            found.append(folder)
            directories.clear()
        else:
            directories[:] = sorted(
                name
                for name in directories
                if not any((folder / name).resolve().is_relative_to(path) for path in excluded)
                and is_directory(folder / name)
            )
    return sorted(found)
