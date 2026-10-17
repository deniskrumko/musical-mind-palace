"""Собирает музыкальные папки в индекс.

Запуск:
    PYTHONPATH=src uv run src/scripts/crawler.py

Документация:
    docs/scripts/crawler.md
"""

import os
import re
import shutil
import sys
from pathlib import Path

from core.duplicates import numbered_path
from core.file_extensions import MUSIC_EXTENSIONS
from core.logicx import is_directory, is_file, is_logicx
from index import INDEX_FILENAME, Index
from scripts import INDEX_DIR, ROOT_MUSIC_DIR

# Заполните пути перед запуском; относительные пути отсчитываются от текущей папки.
INPUT_MUSIC_DIRS: list[Path] = [
    ROOT_MUSIC_DIR / "Acoustic",
    ROOT_MUSIC_DIR / "BassOnly",
    ROOT_MUSIC_DIR / "Heavy",
    ROOT_MUSIC_DIR / "Piano",
    ROOT_MUSIC_DIR / "Polystra",
    ROOT_MUSIC_DIR / "Todo",
    ROOT_MUSIC_DIR / "Trash",
    ROOT_MUSIC_DIR / "TO IMPORT",
]


def clean_name(name: str) -> str:
    """Удаляет фрагменты в круглых скобках и лишние пробелы из названия."""
    cleaned = name
    while re.search(r"\([^()]*\)", cleaned):
        cleaned = re.sub(r"\([^()]*\)", "", cleaned)
    cleaned = " ".join(cleaned.split())
    return name if cleaned in {"", ".", ".."} else cleaned


def raise_walk_error(error: OSError) -> None:
    """Прерывает поиск при ошибке чтения каталога."""
    raise error


def find_music_dirs(inputs: list[Path], output: Path) -> list[Path]:
    """Находит музыкальные папки, исключая выход, ссылки и содержимое проектов."""
    found: list[Path] = []
    for source in sorted(set(inputs), key=lambda path: (len(path.parts), str(path))):
        if source.is_relative_to(output) or any(source.is_relative_to(item) for item in found):
            continue
        if is_logicx(source):
            continue
        for current, directories, files in os.walk(source, onerror=raise_walk_error):
            folder = Path(current)
            directories[:] = sorted(
                name
                for name in directories
                if not (folder / name).is_symlink() and not (folder / name).is_relative_to(output)
            )
            music_files = any(
                (folder / name).suffix.lower() in MUSIC_EXTENSIONS and is_file(folder / name)
                for name in files
            )
            music_projects = any(is_logicx(Path(name)) for name in directories)
            if music_files or music_projects:
                if output.is_relative_to(folder):
                    raise ValueError(f"Музыкальная папка содержит выходную папку: {folder}")
                found.append(folder)
                directories.clear()
            else:
                directories[:] = [name for name in directories if not is_logicx(Path(name))]
    return found


def merge_directories(source: Path, destination: Path) -> None:
    """Переносит содержимое рекурсивно, сохраняя конфликтующие файлы и проекты."""
    source_index = source / INDEX_FILENAME
    destination_index = destination / INDEX_FILENAME
    if source_index.exists() or source_index.is_symlink():
        incoming = Index.load(source_index)
        combined = Index.load(destination_index)
        combined.merge(incoming)
        combined.save(destination_index)
        source_index.unlink()
    for entry in sorted(source.iterdir()):
        target = destination / entry.name
        if not target.exists() and not target.is_symlink():
            shutil.move(str(entry), str(target))
        elif is_directory(entry) and is_directory(target):
            merge_directories(entry, target)
        else:
            target = numbered_path(
                target,
                preserve_extension=entry.is_file() or is_logicx(entry),
            )
            shutil.move(str(entry), str(target))
    source.rmdir()


def choose_destination(source: Path, destination: Path) -> tuple[Path, bool]:
    """Запрашивает объединение или номерное имя при совпадении названий."""
    if not destination.exists() and not destination.is_symlink():
        return destination, False
    can_merge = is_directory(destination)
    print(f"\nПапка: {source}\nМесто назначения уже существует: {destination}")
    while True:
        options = (
            "[m] объединить, [n] добавить номер, [q] завершить"
            if can_merge
            else "[n] добавить номер, [q] завершить"
        )
        try:
            answer = input(f"{options}: ").strip().lower()
        except EOFError:
            raise KeyboardInterrupt from None
        if answer in {"m", "м", "1"} and can_merge:
            return destination, True
        if answer in {"n", "н", "2"}:
            return numbered_path(destination), False
        if answer in {"", "q", "й"}:
            raise KeyboardInterrupt
        print("Введите один из предложенных вариантов.")


def crawl(root: Path, inputs: list[Path], output: Path) -> int:
    """Проверяет настройки и переносит найденные музыкальные папки в выходной каталог."""
    if not inputs:
        raise ValueError("Заполните INPUT_MUSIC_DIRS в начале скрипта.")
    root = root.expanduser().resolve()
    output = output.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"ROOT_MUSIC_DIR не является директорией: {root}")
    normalized: list[Path] = []
    for item in inputs:
        item = item.expanduser()
        if item.is_symlink():
            continue
        item = item.resolve()
        if item.is_relative_to(output):
            continue
        if not item.exists():
            print(f"Входная папка не найдена, пропускаю: {item}")
            continue
        if not item.is_dir() or not item.is_relative_to(root):
            raise ValueError(f"Вход должен быть директорией внутри ROOT_MUSIC_DIR: {item}")
        normalized.append(item)
    folders = find_music_dirs(normalized, output)
    output.mkdir(parents=True, exist_ok=True)
    moved = 0
    for source in folders:
        destination, merge = choose_destination(source, output / clean_name(source.name))
        index_path = source / INDEX_FILENAME
        index = Index.load(index_path)
        index.set("Original folder", source.relative_to(root).as_posix())
        index.save(index_path)
        if merge:
            merge_directories(source, destination)
        else:
            shutil.move(str(source), str(destination))
        moved += 1
        print(f"Перенесено: {source} → {destination}")
    return moved


def validate_index_directory(output: Path) -> bool:
    """Проверяет наличие индексов у песен и отсутствие индексов во вложенных папках."""
    output = output.expanduser().resolve()
    issues = 0
    for song in sorted(output.iterdir()):
        if not is_directory(song):
            continue
        index_path = song / INDEX_FILENAME
        if index_path.is_symlink() or not index_path.is_file():
            print(f"Не найден файл индекса: {index_path}")
            issues += 1
        for current, directories, files in os.walk(song, onerror=raise_walk_error):
            folder = Path(current)
            directories[:] = sorted(name for name in directories if is_directory(folder / name))
            if folder != song and INDEX_FILENAME in files:
                nested_index = folder / INDEX_FILENAME
                if not nested_index.is_symlink() and nested_index.is_file():
                    print(f"Найдены вложения: {nested_index}")
                    issues += 1
    if issues:
        print(f"Валидация завершена. Найдено нарушений: {issues}.")
    else:
        print("Валидация пройдена: индексы расположены корректно.")
    return issues == 0


def main() -> int:
    """Запускает сбор папок и сообщает об ошибке или отмене."""
    try:
        count = crawl(ROOT_MUSIC_DIR, INPUT_MUSIC_DIRS, INDEX_DIR)
        valid = validate_index_directory(INDEX_DIR)
    except KeyboardInterrupt:
        print("\nПеренос остановлен пользователем.", file=sys.stderr)
        return 130
    except (OSError, ValueError, shutil.Error) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    print(f"Готово. Перенесено папок: {count}.")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
