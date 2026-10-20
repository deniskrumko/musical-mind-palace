"""Раскладывает файлы музыкальных директорий по подпапкам ресурсов.

Запуск:
    PYTHONPATH=src uv run src/scripts/tidy_up_index.py
    PYTHONPATH=src uv run src/scripts/tidy_up_index.py --dry-run

Документация:
    docs/scripts/tidy_up_index.md
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

from core.duplicates import numbered_path
from core.file_extensions import CATEGORY_EXTENSIONS
from core.logicx import is_directory, is_file
from index import INDEX_FILENAME
from index.utils import get_music_dirs, raise_walk_error
from music_dir import MusicDir
from scripts import INDEX_DIR

# Относительные пути отсчитываются от текущей рабочей папки.

EXCLUDE_DIRS: list[Path] = [
    INDEX_DIR / "_НАЙТИ",
]


def remove_empty_subdirectories(folder: Path, dry_run: bool = False) -> None:
    """Удаляет вложенные директории без файлов, учитывая проекты и служебные файлы."""
    folders: list[Path] = []
    for current, directories, _ in os.walk(folder, onerror=raise_walk_error):
        parent = Path(current)
        folders.append(parent)
        directories[:] = sorted(name for name in directories if is_directory(parent / name))

    nonempty: set[Path] = set()
    for parent in reversed(folders):
        if any(is_file(entry) or entry in nonempty for entry in parent.iterdir()):
            nonempty.add(parent)
        elif parent != folder:
            if not dry_run:
                shutil.rmtree(parent)
            action = "Будет удалена пустая папка" if dry_run else "Удалена пустая папка"
            print(f"{action}: {parent}")


def tidy_up_index(index_dir: Path, dry_run: bool = False) -> int:
    """Удаляет пустые подпапки и раскладывает файлы музыкальных папок по категориям."""
    moved = 0
    reserved: set[Path] = set()
    for folder in get_music_dirs(index_dir, exclude_dirs=EXCLUDE_DIRS):
        remove_empty_subdirectories(folder, dry_run=dry_run)
        for entry in MusicDir(path=folder).other_files:
            category = next(
                (
                    name
                    for name, extensions in CATEGORY_EXTENSIONS.items()
                    if entry.suffix.lower() in extensions
                ),
                None,
            )
            if category is None:
                continue
            destination = folder / category
            if destination.is_symlink() or (destination.exists() and not is_directory(destination)):
                raise ValueError(f"Путь категории не является обычной директорией: {destination}")
            target = numbered_path(
                destination / entry.name, preserve_extension=True, reserved=reserved
            )
            reserved.add(target)
            if not dry_run:
                destination.mkdir(exist_ok=True)
                shutil.move(str(entry), str(target))
            moved += 1
            action = "Будет перемещено" if dry_run else "Перенесено"
            print(f"{action}: {entry} → {target}")
    return moved


def has_resource_files(folder: Path) -> bool:
    """Проверяет наличие файлов кроме индексов, учитывая вложения и пакеты Logic."""
    for current, directories, files in os.walk(folder, onerror=raise_walk_error):
        parent = Path(current)
        if any(name != INDEX_FILENAME and is_file(parent / name) for name in files + directories):
            return True
        directories[:] = [name for name in directories if is_directory(parent / name)]
    return False


def print_attention_folders(index_dir: Path) -> None:
    """Выводит списки музыкальных папок, требующих внимания после сортировки."""
    other_files: list[Path] = []
    subdirs: list[Path] = []
    empty: list[Path] = []

    for folder in get_music_dirs(index_dir, exclude_dirs=EXCLUDE_DIRS):
        music = MusicDir(path=folder)
        if music.other_files:
            other_files.append(folder)
        if music.subdirs:
            subdirs.append(folder)
        if not has_resource_files(folder):
            empty.append(folder)

    for title, folders in (
        ("Папки с other_files", other_files),
        ("Папки с subdirs", subdirs),
        ("Папки без файлов кроме индекса", empty),
    ):
        print(f"\n{title}:")
        if folders:
            for folder in folders:
                print(f"- {folder}")
        else:
            print("- нет")


def print_category_warnings(index_dir: Path) -> None:
    """Предупреждает о файлах с неподходящими расширениями в папках категорий."""
    warnings: list[tuple[Path, str, set[str]]] = []
    for folder in get_music_dirs(index_dir, exclude_dirs=EXCLUDE_DIRS):
        for category, extensions in CATEGORY_EXTENSIONS.items():
            category_dir = folder / category
            if not is_directory(category_dir):
                continue
            for current, directories, files in os.walk(category_dir, onerror=raise_walk_error):
                parent = Path(current)
                entries = [parent / name for name in files + directories]
                for entry in entries:
                    if is_file(entry) and entry.suffix.lower() not in extensions:
                        warnings.append((entry, category, extensions))
                directories[:] = [name for name in directories if is_directory(parent / name)]

    print("\nПредупреждения о расширениях в папках категорий:")
    if not warnings:
        print("- нет")
        return
    for path, category, extensions in warnings:
        allowed = ", ".join(sorted(extensions))
        print(f"- {path}: папка {category}, допустимы расширения {allowed}")


def main(argv: list[str] | None = None) -> int:
    """Запускает сортировку и сообщает об ошибках или отмене."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать план очистки и перемещений без изменений на диске.",
    )
    args = parser.parse_args(argv)
    try:
        count = tidy_up_index(INDEX_DIR, dry_run=args.dry_run)
        if args.dry_run:
            print(f"План готов. Будет перемещено файлов: {count}.")
            print("\nТекущее состояние папок (dry-run):")
        else:
            print(f"Готово. Перенесено файлов: {count}.")
        print_category_warnings(INDEX_DIR)
        print_attention_folders(INDEX_DIR)
    except KeyboardInterrupt:
        print("\nСортировка остановлена пользователем.", file=sys.stderr)
        return 130
    except (OSError, ValueError, shutil.Error) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
