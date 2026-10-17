"""Поиск музыкальных директорий по файлу индекса."""

import os
from collections.abc import Iterable
from pathlib import Path

from core.logicx import is_directory
from index.resources import INDEX_FILENAME


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
