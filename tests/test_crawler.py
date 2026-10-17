"""Проверки поиска и переноса музыкальных папок на временных данных."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from index import Index
from scripts import crawler
from scripts.crawler import clean_name, crawl, find_music_dirs, validate_index_directory


def music(folder: Path, filename: str = "track.mp3") -> Path:
    """Создаёт временную музыкальную папку с файлом для проверки."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text("музыка")
    return folder


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("Hello (test)", "Hello"),
        ("Hello (demo (old)) (2024)", "Hello"),
        ("(demo)", "(demo)"),
        (" A   B ", "A B"),
    ],
)
def test_clean_name(original: str, expected: str) -> None:
    """Очищает скобки и пробелы, сохраняя непустое имя."""
    assert clean_name(original) == expected


def test_discovery_excludes_children_output_and_links(tmp_path: Path) -> None:
    """Не выделяет дочерние песни и не обходит выходную папку и ссылки."""
    source = music(tmp_path / "Song", "TRACK.M4A")
    music(source / "Nested")
    output = tmp_path / "Index"
    music(output / "Existing")
    external = music(tmp_path / "External")
    (tmp_path / "Link").symlink_to(external, target_is_directory=True)
    assert find_music_dirs([tmp_path, source, tmp_path], output) == [external, source]


@pytest.mark.parametrize("extension", [".LOGICX", ".BAND"])
def test_logic_project_is_atomic(tmp_path: Path, extension: str) -> None:
    """Распознаёт пакет Logic Pro и переносит его вместе с внешней папкой."""
    source = tmp_path / "Input" / "Hello (test)"
    music(source / f"Session{extension}" / "Media")
    output = tmp_path / "Index"
    assert crawl(tmp_path, [tmp_path / "Input"], output) == 1
    destination = output / "Hello"
    assert (destination / f"Session{extension}" / "Media" / "track.mp3").is_file()
    assert Index.load(destination / "INDEX.md").tags["Original folder"] == "Input/Hello (test)"
    assert not source.exists()


@pytest.mark.parametrize("extension", [".logicx", ".band"])
def test_merge_preserves_files_projects_and_unique_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
    """Объединяет вложенные папки и индексы без перезаписи файлов и пакетов."""
    source = music(tmp_path / "Input" / "Hello (new)")
    destination = music(tmp_path / "Index" / "Hello")
    (source / "INDEX.md").write_text(
        "Новое описание\n\n## Mood\nНовое\n## Original folder\nСтарый путь\n"
    )
    (destination / "INDEX.md").write_text("Описание\n\n## Mood\nСтарое\n## Keep\nДа\n")
    music(source / f"Session{extension}")
    music(destination / f"Session{extension}")
    music(source / "Assets")
    music(destination / "Assets")
    monkeypatch.setattr("builtins.input", lambda _: "m")
    assert crawl(tmp_path, [source.parent], destination.parent) == 1
    assert not source.exists()
    assert (destination / "track (2).mp3").read_text() == "музыка"
    assert (destination / "Assets" / "track (2).mp3").is_file()
    assert (destination / f"Session (2){extension}" / "track.mp3").is_file()
    index = Index.load(destination / "INDEX.md")
    assert index.tags == {
        "Mood": "Новое",
        "Keep": "Да",
        "Original folder": "Input/Hello (new)",
    }
    assert "Новое описание" in index.description


def test_numbered_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Выбирает следующий свободный номер при отказе от объединения."""
    source = music(tmp_path / "Input" / "Hello (demo)")
    output = tmp_path / "Index"
    music(output / "Hello")
    music(output / "Hello (2)")
    monkeypatch.setattr("builtins.input", lambda _: "n")
    crawl(tmp_path, [source.parent], output)
    assert (output / "Hello (3)" / "track.mp3").is_file()


def test_cancel_leaves_source_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Отменяет перенос до изменения индекса исходной папки."""
    source = music(tmp_path / "Input" / "Hello")
    output = tmp_path / "Index"
    music(output / "Hello")
    monkeypatch.setattr("builtins.input", lambda _: "")
    with pytest.raises(KeyboardInterrupt):
        crawl(tmp_path, [source.parent], output)
    assert (source / "track.mp3").is_file()
    assert not (source / "INDEX.md").exists()


def test_output_inside_music_folder_is_rejected(tmp_path: Path) -> None:
    """Отклоняет перенос папки, внутри которой находится выходной каталог."""
    source = music(tmp_path / "Song")
    with pytest.raises(ValueError, match="содержит выходную"):
        crawl(tmp_path, [source], source / "Index")
    assert (source / "track.mp3").is_file()
    assert not (source / "INDEX.md").exists()


def test_input_outside_root_is_rejected(tmp_path: Path) -> None:
    """Проверяет принадлежность всех входов корню до переноса."""
    root = tmp_path / "Root"
    source = music(root / "Song")
    outside = music(tmp_path / "Outside")
    with pytest.raises(ValueError, match="внутри ROOT_MUSIC_DIR"):
        crawl(root, [source, outside], tmp_path / "Index")
    assert source.exists()


def test_missing_input_is_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Сообщает об отсутствующем входе и переносит папки из существующего."""
    missing = tmp_path / "Missing"
    source = music(tmp_path / "Input" / "Song")
    output = tmp_path / "Index"
    assert crawl(tmp_path, [missing, source.parent], output) == 1
    assert (output / "Song" / "INDEX.md").is_file()
    message = capsys.readouterr().out
    assert "не найдена" in message
    assert str(missing) in message


def test_all_inputs_missing(tmp_path: Path) -> None:
    """Создаёт выходной каталог и завершает поиск при отсутствии всех входов."""
    output = tmp_path / "Index"
    assert crawl(tmp_path, [tmp_path / "Missing"], output) == 0
    assert validate_index_directory(output)


def test_validation_accepts_correct_structure(tmp_path: Path) -> None:
    """Допускает вложенные папки без индексов и не обходит символические ссылки."""
    song = music(tmp_path / "Index" / "Song")
    (song / "INDEX.md").write_text("Описание")
    music(song / "Assets")
    external = music(tmp_path / "External")
    (external / "INDEX.md").write_text("Внешний индекс")
    (song / "Link").symlink_to(external, target_is_directory=True)
    assert validate_index_directory(song.parent)


@pytest.mark.parametrize("extension", [".logicx", ".band"])
def test_validation_reports_missing_and_nested_indices(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extension: str
) -> None:
    """Выводит отсутствующий индекс и все вложенные индексы на любой глубине."""
    output = tmp_path / "Index"
    missing = music(output / "Missing")
    song = music(output / "Song")
    (song / "INDEX.md").write_text("Описание")
    nested = music(song / "Nested")
    project = music(nested / f"Session{extension}" / "Media")
    for folder in (nested, project):
        (folder / "INDEX.md").write_text("Вложенный индекс")
    assert not validate_index_directory(output)
    message = capsys.readouterr().out
    assert str(missing / "INDEX.md") in message
    assert f"Найдены вложения: {nested / 'INDEX.md'}" in message
    assert str(project / "INDEX.md") not in message
    assert "Найдено нарушений: 2" in message


def test_main_validates_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Запускает валидацию после поиска даже без найденных входных папок."""
    output = tmp_path / "Index"
    song = music(output / "MissingIndex")
    monkeypatch.setattr(crawler, "ROOT_MUSIC_DIR", tmp_path)
    monkeypatch.setattr(crawler, "INPUT_MUSIC_DIRS", [tmp_path / "MissingInput"])
    monkeypatch.setattr(crawler, "INDEX_DIR", output)
    assert crawler.main() == 1
    assert f"Не найден файл индекса: {song / 'INDEX.md'}" in capsys.readouterr().out


def test_direct_script_launch(tmp_path: Path) -> None:
    """Проверяет прямой запуск временной копии без доступа к библиотеке пользователя."""
    project = Path(__file__).resolve().parents[1]
    shutil.copytree(project / "src", tmp_path / "src")
    script = tmp_path / "src/scripts/crawler.py"
    script.write_text(
        script.read_text(encoding="utf-8").replace(
            'if __name__ == "__main__":',
            'if __name__ == "__main__":\n    INPUT_MUSIC_DIRS = []',
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Заполните INPUT_MUSIC_DIRS" in result.stderr


@pytest.mark.parametrize("extension", [".gp4", ".GP5", ".gpt"])
def test_discovery_supports_all_tab_formats(tmp_path: Path, extension: str) -> None:
    """Распознаёт папку по табулатуре каждого дополнительно поддерживаемого формата."""
    source = music(tmp_path / "Song", f"track{extension}")
    assert find_music_dirs([tmp_path], tmp_path / "Index") == [source]
