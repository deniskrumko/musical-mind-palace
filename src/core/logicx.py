"""Общие проверки файлов и каталогов с учётом проектов из CATEGORY_EXTENSIONS["logic"]."""

from pathlib import Path

from core.file_extensions import CATEGORY_EXTENSIONS


def is_logicx(path: Path) -> bool:
    """Определяет проект по CATEGORY_EXTENSIONS["logic"] без учёта регистра."""
    return path.suffix.lower() in CATEGORY_EXTENSIONS["logic"]


def is_file(path: Path) -> bool:
    """Распознаёт файл или проект, исключая ссылки, .DS_Store и бэкапы Guitar Pro."""
    return (
        path.name != ".DS_Store"
        and not (path.name.startswith(".") and path.name.endswith(".bak") and len(path.name) > 5)
        and not path.is_symlink()
        and (path.is_file() or (is_logicx(path) and path.is_dir()))
    )


def is_directory(path: Path) -> bool:
    """Распознаёт обычную директорию, исключая проекты Logic Pro, GarageBand и ссылки."""
    return not path.is_symlink() and not is_logicx(path) and path.is_dir()
