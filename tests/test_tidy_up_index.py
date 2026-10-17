"""Проверки сортировки ресурсов, поиска песен и сохранности исходных данных."""

import os
from pathlib import Path

import pytest

from core.duplicates import numbered_path
from core.file_extensions import CATEGORY_EXTENSIONS
from core.logicx import is_directory, is_file, is_logicx
from index.utils import get_music_dirs
from music_dir import MusicDir
from scripts import tidy_up_index as script


def song(path: Path) -> Path:
    """Создаёт музыкальную директорию с индексом."""
    path.mkdir(parents=True)
    (path / "INDEX.md").write_text("Описание", encoding="utf-8")
    return path


def test_discovery_stops_at_song_and_excludes_projects_and_links(tmp_path: Path) -> None:
    """Находит вложенные песни, не обходя содержимое песен, проектов и ссылок."""
    first = song(tmp_path / "Group" / "A")
    second = song(tmp_path / "B")
    song(first / "Nested")
    song(tmp_path / "Project.LOGICX" / "Inside")
    (tmp_path / "Link").symlink_to(first, target_is_directory=True)
    linked_index = tmp_path / "LinkedIndex"
    linked_index.mkdir()
    (linked_index / "INDEX.md").symlink_to(first / "INDEX.md")
    assert get_music_dirs(tmp_path) == sorted([first, second])
    assert get_music_dirs(first) == [first]
    with pytest.raises(ValueError):
        get_music_dirs(tmp_path / "Link")
    with pytest.raises(ValueError):
        get_music_dirs(tmp_path / "Missing")


def test_sorting_preserves_content_and_is_repeatable(tmp_path: Path) -> None:
    """Раскладывает все форматы, сохраняя дубли, проекты и неподдерживаемые файлы."""
    folder = song(tmp_path / "Song")
    names = ["voice.M4A", "mix.mp3", "a.gp", "b.GPX", "c.gp5", "d.gp4", "e.gpt"]
    for name in names:
        (folder / name).write_text(name)
    project = folder / "Session.LOGICX"
    project.mkdir()
    (project / "INDEX.md").write_text("Внутренний индекс")
    (folder / "bounce").mkdir()
    (folder / "bounce" / "mix.mp3").write_text("Старый микс")
    (folder / "bounce" / "mix (2).mp3").write_text("Второй микс")
    (folder / "logic").mkdir()
    (folder / "logic" / project.name).mkdir()
    nested = song(folder / "Nested")
    (nested / "keep.mp3").write_text("Вложенный микс")
    (folder / "pretend.mp3").mkdir()
    (folder / "notes.txt").write_text("Заметки")
    (folder / "linked.mp3").symlink_to(folder / "notes.txt")
    assert script.tidy_up_index(tmp_path) == 8
    resources = MusicDir(path=folder)
    assert [path.name for path in resources.dict_files] == ["voice.M4A"]
    assert [path.name for path in resources.bounce_files] == [
        "mix (2).mp3",
        "mix (3).mp3",
        "mix.mp3",
    ]
    assert [path.name for path in resources.tab_files] == names[2:]
    assert (folder / "logic" / "Session (2).LOGICX" / "INDEX.md").read_text() == "Внутренний индекс"
    assert (folder / "bounce" / "mix (3).mp3").read_text() == "mix.mp3"
    assert (folder / "bounce" / "mix.mp3").read_text() == "Старый микс"
    assert resources.other_files == [folder / "notes.txt"]
    assert resources.subdirs == [nested]
    assert not (folder / "pretend.mp3").exists()
    assert (nested / "keep.mp3").is_file()
    assert (folder / "linked.mp3").is_symlink()
    assert (folder / "INDEX.md").read_text() == "Описание"
    assert script.tidy_up_index(tmp_path) == 0


def test_properties_filter_formats_depth_and_links(tmp_path: Path) -> None:
    """Читает актуальные списки только непосредственных ресурсов без ссылок."""
    folder = song(tmp_path / "Song")
    resources = MusicDir(path=folder)
    assert (
        resources.dict_files
        == resources.bounce_files
        == resources.logic_files
        == resources.tab_files
        == []
    )
    (folder / "dict").mkdir()
    (folder / "dict" / "b.m4a").write_text("b")
    (folder / "dict" / "a.M4A").write_text("a")
    (folder / "dict" / "notes.txt").write_text("текст")
    (folder / "dict" / "fake.m4a").mkdir()
    (folder / "dict" / "fake.m4a" / "nested.m4a").touch()
    (folder / "dict" / "link.m4a").symlink_to(folder / "dict" / "a.M4A")
    assert resources.dict_files == [folder / "dict" / "a.M4A", folder / "dict" / "b.m4a"]
    (folder / "root.logicx").mkdir()
    (folder / "file.LOGICX").touch()
    assert resources.other_files == [folder / "file.LOGICX", folder / "root.logicx"]
    assert resources.subdirs == []
    (folder / "logic").mkdir()
    (folder / "logic" / "Project.logicx").mkdir()
    (folder / "logic" / "flat.logicx").touch()
    assert resources.logic_files == [
        folder / "logic" / "Project.logicx",
        folder / "logic" / "flat.logicx",
    ]
    (folder / "bounce").symlink_to(folder / "dict", target_is_directory=True)
    assert resources.bounce_files == []


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling"])
def test_category_obstacle_stops_without_moving_file(tmp_path: Path, kind: str) -> None:
    """Останавливает сортировку при занятом или небезопасном пути категории."""
    folder = song(tmp_path / "Song")
    original = folder / "track.mp3"
    original.write_text("микс")
    target = folder / "bounce"
    if kind == "file":
        target.write_text("занято")
    else:
        target.symlink_to(tmp_path if kind == "symlink" else tmp_path / "Missing")
    with pytest.raises(ValueError, match="категории"):
        script.tidy_up_index(tmp_path)
    assert original.read_text() == "микс"


def test_empty_song_does_not_create_categories(tmp_path: Path) -> None:
    """Не создаёт пустые категории в папке без поддерживаемых файлов."""
    folder = song(tmp_path / "Song")
    assert script.tidy_up_index(tmp_path) == 0
    assert list(folder.iterdir()) == [folder / "INDEX.md"]


@pytest.mark.parametrize("dry_run", [False, True])
def test_empty_subdirectories_cleanup(
    tmp_path: Path, dry_run: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    """Очищает пустые вложения, сохраняя индексы, ресурсы, проекты и внешние файлы."""
    folder = song(tmp_path / "Song")
    empty = folder / "Empty" / "Nested"
    empty.mkdir(parents=True)
    (empty / ".DS_Store").touch()
    (empty / ".song.gp5.bak").touch()
    category = folder / "bounce"
    category.mkdir()
    outside = tmp_path / "Outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("Сохранить")
    (empty / "Link").symlink_to(outside, target_is_directory=True)
    indexed = song(folder / "Indexed")
    resources = folder / "Resources" / "Nested"
    resources.mkdir(parents=True)
    (resources / "notes.txt").touch()
    projects = folder / "logic"
    projects.mkdir()
    for extension in CATEGORY_EXTENSIONS["logic"]:
        project = projects / f"Session{extension}"
        (project / "Empty").mkdir(parents=True)

    assert script.tidy_up_index(tmp_path, dry_run=dry_run) == 0
    output = capsys.readouterr().out
    for path in (empty, empty.parent, category):
        assert path.exists() == dry_run
        assert str(path) in output
    assert (folder / "INDEX.md").is_file()
    assert (indexed / "INDEX.md").is_file()
    assert (resources / "notes.txt").is_file()
    assert (outside / "keep.txt").read_text() == "Сохранить"
    for extension in CATEGORY_EXTENSIONS["logic"]:
        assert (projects / f"Session{extension}" / "Empty").is_dir()


def test_numbering_respects_dangling_links_and_extension(tmp_path: Path) -> None:
    """Считает оборванные ссылки занятыми именами и сохраняет расширение файла."""
    path = tmp_path / "track.mp3"
    assert numbered_path(path, preserve_extension=True) == path
    path.symlink_to(tmp_path / "missing")
    (tmp_path / "track (2).mp3").mkdir()
    assert numbered_path(path, preserve_extension=True) == tmp_path / "track (3).mp3"
    assert numbered_path(path) == tmp_path / "track.mp3 (2)"


def test_logicx_file_semantics(tmp_path: Path) -> None:
    """Считает пакеты и обычные проекты файлами, исключая ссылки и отсутствующие пути."""
    project = tmp_path / "Project.LOGICX"
    assert is_logicx(project)
    assert not is_file(project)
    project.mkdir()
    assert is_file(project)
    assert not is_directory(project)
    (tmp_path / "Link.logicx").symlink_to(project, target_is_directory=True)
    assert not is_file(tmp_path / "Link.logicx")
    assert not is_directory(tmp_path / "Link.logicx")


def test_main_reports_result_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Возвращает код успеха или ошибки для настроенного каталога."""
    monkeypatch.setattr(script, "INDEX_DIR", tmp_path)
    assert script.main([]) == 0
    monkeypatch.setattr(script, "INDEX_DIR", tmp_path / "Missing")
    assert script.main([]) == 1


def test_excluded_directories_are_not_traversed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Не открывает исключённые папки и сохраняет файлы внутри них без изменений."""
    excluded = tmp_path / "_НАЙТИ"
    nested = song(excluded / "Nested")
    direct = song(tmp_path / "SkipSong")
    allowed = song(tmp_path / "_НАЙТИ_другое")
    for folder in (nested, direct, allowed):
        (folder / "track.mp3").write_text("микс")
    original_scandir = os.scandir

    def guarded_scandir(path):
        """Выявляет попытку чтения исключённой директории."""
        assert not Path(path).is_relative_to(excluded)
        assert not Path(path).is_relative_to(direct)
        return original_scandir(path)

    monkeypatch.setattr("os.scandir", guarded_scandir)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(script, "EXCLUDE_DIRS", [Path("_НАЙТИ"), direct])
    assert script.tidy_up_index(tmp_path) == 1
    assert (allowed / "bounce" / "track.mp3").read_text() == "микс"
    for folder in (nested, direct):
        assert (folder / "track.mp3").read_text() == "микс"
        assert not (folder / "bounce").exists()
    assert get_music_dirs(excluded, exclude_dirs=[excluded]) == []
    assert get_music_dirs(nested, exclude_dirs=[excluded]) == []


def test_main_reports_attention_folders_after_sorting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Выводит итоговые списки, различая пустые папки, вложения и проекты Logic."""
    empty = song(tmp_path / "Empty")
    empty_subdir = song(tmp_path / "EmptySubdir")
    (empty_subdir / "Assets").mkdir()
    other = song(tmp_path / "Other")
    (other / "notes.txt").touch()
    nested = song(tmp_path / "Nested")
    (nested / "Assets").mkdir()
    (nested / "Assets" / "audio.wav").touch()
    sorted_song = song(tmp_path / "Sorted")
    (sorted_song / "track.mp3").touch()
    project = song(tmp_path / "Logic")
    (project / "Session.logicx").mkdir()
    unusual_category = song(tmp_path / "UnusualCategory")
    (unusual_category / "dict").mkdir()
    (unusual_category / "dict" / "notes.txt").touch()
    excluded = song(tmp_path / "Excluded")
    monkeypatch.setattr(script, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(script, "EXCLUDE_DIRS", [excluded])
    assert script.main([]) == 0
    output = capsys.readouterr().out
    summary = output.split("Готово. Перенесено файлов: 2.")[1]
    other_report, rest = summary.split("Папки с subdirs:")
    subdir_report, empty_report = rest.split("Папки без файлов кроме индекса:")
    assert other_report.splitlines() == ["", "", "Папки с other_files:", f"- {other}", ""]
    assert subdir_report.splitlines() == ["", f"- {nested}", ""]
    assert empty_report.splitlines() == ["", f"- {empty}", f"- {empty_subdir}"]
    assert str(excluded) not in summary


def test_attention_report_marks_empty_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Явно отмечает отсутствие папок в каждой группе отчёта."""
    script.print_attention_folders(tmp_path)
    assert capsys.readouterr().out.count("- нет") == 3


def test_dry_run_matches_real_destinations_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Планирует точные имена дублей, не вызывая создание папок и перемещение."""
    folder = song(tmp_path / "Song")
    (folder / "mix.mp3").write_text("микс")
    (folder / "mix (2).mp3").write_text("второй")
    (folder / "voice.m4a").write_text("запись")
    project = folder / "Session.logicx"
    project.mkdir()
    (project / "data").write_text("проект")
    (folder / "bounce").mkdir()
    (folder / "bounce" / "mix.mp3").write_text("старый")
    before = sorted(folder.rglob("*"))
    monkeypatch.setattr(script, "INDEX_DIR", tmp_path)

    def forbidden_write(*args, **kwargs):
        """Отклоняет попытку записи в режиме предварительного просмотра."""
        pytest.fail("dry-run попытался изменить диск")

    with monkeypatch.context() as guarded:
        guarded.setattr(script.shutil, "move", forbidden_write)
        guarded.setattr(Path, "mkdir", forbidden_write)
        assert script.main(["--dry-run"]) == 0
    preview = capsys.readouterr().out
    planned = [
        line.split(": ", 1)[1]
        for line in preview.splitlines()
        if line.startswith("Будет перемещено:")
    ]
    assert len(planned) == 4
    assert f"{folder / 'mix.mp3'} → {folder / 'bounce' / 'mix (3).mp3'}" in planned
    assert "План готов. Будет перемещено файлов: 4." in preview
    assert "Текущее состояние папок (dry-run):" in preview
    assert sorted(folder.rglob("*")) == before
    assert (folder / "mix.mp3").read_text() == "микс"
    assert (project / "data").read_text() == "проект"
    assert script.tidy_up_index(tmp_path) == 4
    actual = [
        line.split(": ", 1)[1]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("Перенесено:")
    ]
    assert planned == actual


def test_ds_store_is_not_a_resource_file(tmp_path: Path) -> None:
    """Исключает .DS_Store из ресурсов и проверки файлов во вложениях."""
    folder = song(tmp_path / "Song")
    metadata = folder / ".DS_Store"
    metadata.write_bytes(b"metadata")
    nested = folder / "Assets"
    nested.mkdir()
    (nested / ".DS_Store").touch()
    assert not is_file(metadata)
    assert MusicDir(path=folder).other_files == []
    assert not script.has_resource_files(folder)
    assert script.tidy_up_index(tmp_path) == 0
    assert metadata.read_bytes() == b"metadata"
    assert not nested.exists()
    nested.mkdir()
    (nested / "notes.txt").touch()
    assert script.has_resource_files(folder)


def test_image_sorting_and_resources(tmp_path: Path) -> None:
    """Сортирует изображения и читает только файлы непосредственно из image."""
    folder = song(tmp_path / "Song")
    resources = MusicDir(path=folder)
    assert resources.image_files == []
    names = [
        "a.JPG",
        "b.jpeg",
        "c.webp",
        "d.png",
        "e.gif",
        "f.bmp",
        "i.heic",
        "j.heif",
    ]
    for name in names:
        (folder / name).write_text(name)
    assert script.tidy_up_index(tmp_path) == len(names)
    images = folder / "image"
    assert resources.image_files == [images / name for name in names]
    assert resources.subdirs == []
    assert resources.other_files == []
    (images / "notes.txt").touch()
    (images / "Nested").mkdir()
    (images / "Nested" / "hidden.jpg").touch()
    (images / "link.jpg").symlink_to(images / "a.JPG")
    assert resources.image_files == [images / name for name in names]
    assert script.tidy_up_index(tmp_path) == 0


@pytest.mark.parametrize("extension", [".logicx", ".BAND"])
def test_project_packages_use_shared_extensions(
    tmp_path: Path, extension: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Применяет общие исключения к поиску, ресурсам и переносу каждого типа проекта."""
    folder = song(tmp_path / "Song")
    project = folder / f"Session{extension}"
    song(project / "Media")
    resources = MusicDir(path=folder)
    assert resources.other_files == [project]
    assert resources.subdirs == []
    assert script.has_resource_files(folder)
    assert get_music_dirs(tmp_path) == [folder]
    with pytest.raises(ValueError):
        get_music_dirs(project)
    assert is_logicx(project)
    assert is_file(project)
    assert not is_directory(project)
    assert script.tidy_up_index(tmp_path, dry_run=True) == 1
    assert project.is_dir()
    assert script.tidy_up_index(tmp_path) == 1
    target = folder / "logic" / project.name
    assert resources.logic_files == [target]
    assert (target / "Media" / "INDEX.md").is_file()
    assert resources.other_files == []
    assert resources.subdirs == []
    assert get_music_dirs(tmp_path) == [folder]
    monkeypatch.setitem(CATEGORY_EXTENSIONS, "logic", {".testproject"})
    future = folder / "Future.testproject"
    future.mkdir()
    assert is_logicx(future)
    assert is_file(future)
    assert not is_directory(future)
    assert script.tidy_up_index(tmp_path) == 1
    assert resources.logic_files == [folder / "logic" / future.name]


@pytest.mark.parametrize("filename", [".song.bak", ".song.gp5.bak", ".песня.gpx.bak"])
def test_guitar_pro_backups_are_not_resource_files(tmp_path: Path, filename: str) -> None:
    """Исключает скрытые бэкапы Guitar Pro из ресурсов и проверки пустых папок."""
    folder = song(tmp_path / "Song")
    backup = folder / filename
    backup.write_text("бэкап")
    assert not is_file(backup)
    assert MusicDir(path=folder).other_files == []
    assert not script.has_resource_files(folder)
    assert script.tidy_up_index(tmp_path) == 0
    assert backup.read_text() == "бэкап"


@pytest.mark.parametrize("filename", ["song.bak", ".bak", ".song.gp5"])
def test_backup_filter_keeps_other_files(tmp_path: Path, filename: str) -> None:
    """Сохраняет файлы, не соответствующие шаблону скрытого бэкапа Guitar Pro."""
    path = tmp_path / filename
    path.touch()
    assert is_file(path)
