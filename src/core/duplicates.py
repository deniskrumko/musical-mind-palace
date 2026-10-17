"""Подбор свободных имён при совпадении путей."""

from collections.abc import Collection
from pathlib import Path


def numbered_path(
    path: Path, preserve_extension: bool = False, reserved: Collection[Path] = ()
) -> Path:
    """Подбирает свободное имя с номером начиная с двух."""
    suffix = path.suffix if preserve_extension else ""
    stem = path.name[: -len(suffix)] if suffix else path.name
    candidate = path
    number = 2
    while candidate in reserved or candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{stem} ({number}){suffix}")
        number += 1
    return candidate
