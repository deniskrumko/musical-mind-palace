"""Проверки совместного сохранения имени аудиофайла и сведений музыкальной директории."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_web_player import make_song, metadata_payload

from index import Index
from web_player.app import create_app
from web_player.renaming import link_audio, remove_audio_link, renamed_audio

RenameEditor = tuple[Path, TestClient, str, dict]


@pytest.fixture
def rename_editor(tmp_path: Path) -> Iterator[RenameEditor]:
    """Открывает редактор первой записи временной библиотеки с несколькими файлами."""
    root = tmp_path / "library"
    folder = make_song(root, "А", ("bounce/1.mp3", "bounce/2.mp3"))
    make_song(root, "Б", ("bounce/3.mp3",))
    with TestClient(create_app(root)) as client:
        track = client.get("/api/state").json()["current"]
        url = f"/api/metadata/{track['id']}"
        yield folder, client, url, client.get(url).json()


def test_rename_preserves_track_audio_and_queue(rename_editor: RenameEditor) -> None:
    """Меняет только выбранный файл, сохраняя его ID, аудиоадрес и порядок очереди."""
    folder, client, url, data = rename_editor
    before = client.get("/api/state").json()
    playlist = client.get("/api/playlist").json()
    original = folder / "bounce/1.mp3"
    target = folder / "bounce/Новая запись.v2.mp3"
    info = original.stat()
    assert data["filename"] == "1"
    assert data["extension"] == ".mp3"
    assert data["track_id"] == before["current"]["id"]
    with original.open("rb") as playing:
        assert playing.read(2) == b"01"
        response = client.put(
            url,
            json=metadata_payload(
                data, filename="Новая запись.v2", description="Описание", tags={"rating": 7}
            ),
        )
        assert response.status_code == 200
        assert playing.read() == b"23456789"
    saved = response.json()
    assert saved["filename"] == "Новая запись.v2"
    assert saved["file_revision"] != data["file_revision"]
    assert not original.exists()
    assert target.stat().st_ino == info.st_ino
    assert target.read_bytes() == b"0123456789"
    assert (folder / "bounce/2.mp3").exists()
    assert Index.load(folder / "INDEX.md").tags["rating"].value == 7
    assert client.get(url).json() == saved
    after = client.get("/api/state").json()
    assert after["current"]["id"] == before["current"]["id"]
    assert after["current"]["name"] == target.name
    assert [track["id"] for track in after["upcoming"]] == [
        track["id"] for track in before["upcoming"]
    ]
    assert after["previous"] == before["previous"]
    assert after["ended"] == before["ended"]
    page = client.get("/api/playlist").json()
    assert page["revision"] == playlist["revision"]
    assert [track["id"] for track in page["tracks"]] == [
        track["id"] for track in playlist["tracks"]
    ]
    assert [track["name"] for track in page["tracks"]] == [target.name, "2.mp3", "3.mp3"]
    assert page["tracks"][1]["tags"] == after["current"]["tags"]
    assert page["tracks"][2]["tags"] == []
    audio = client.get(f"/audio/{data['track_id']}", headers={"Range": "bytes=3-6"})
    assert audio.status_code == 206
    assert audio.content == b"3456"
    with (
        patch("web_player.app.sys.platform", "darwin"),
        patch("web_player.app.subprocess.run") as run,
    ):
        assert client.post(f"/api/reveal/{data['track_id']}").status_code == 204
        assert run.call_args.args[0][-1] == str(target)


def test_unchanged_filename_does_not_rename(rename_editor: RenameEditor) -> None:
    """Сохраняет теги без операций переименования, если имя осталось прежним."""
    folder, client, url, data = rename_editor
    original = folder / "bounce/1.mp3"
    with patch("web_player.renaming.link_audio") as link:
        response = client.put(url, json=metadata_payload(data, tags={"rating": 9}))
        assert response.status_code == 200
        link.assert_not_called()
    assert response.json()["file_revision"] == data["file_revision"]
    assert original.read_bytes() == b"0123456789"


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "broken_symlink", "hardlink"])
def test_rename_rejects_occupied_name(rename_editor: RenameEditor, kind: str) -> None:
    """Отклоняет занятые имена без изменения исходного аудио, индекса и очереди."""
    folder, client, url, data = rename_editor
    original = folder / "bounce/1.mp3"
    target = folder / "bounce/Занято.mp3"
    if kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        target.symlink_to(original)
    elif kind == "broken_symlink":
        target.symlink_to(folder / "missing.mp3")
    elif kind == "hardlink":
        target.hardlink_to(original)
    else:
        target.write_bytes(b"other audio")
    data = client.get(url).json()
    before = client.get("/api/state").json()
    response = client.put(
        url, json=metadata_payload(data, filename="Занято", description="Новый текст")
    )
    assert response.status_code == 409
    assert "уже существует" in response.json()["detail"]
    assert original.read_bytes() == b"0123456789"
    if kind == "file":
        assert target.read_bytes() == b"other audio"
    assert (folder / "INDEX.md").read_bytes() == b""
    assert client.get("/api/state").json() == before
    assert list((folder / "bounce").glob(".rename-*")) == []


@pytest.mark.parametrize("filename", ["", " ", ".", "..", "../song", "a/b", "a\\b", "a\n", "a\0"])
def test_rename_rejects_invalid_filename(rename_editor: RenameEditor, filename: str) -> None:
    """Не допускает пустые имена, выход из папки и управляющие символы в имени."""
    folder, client, url, data = rename_editor
    response = client.put(
        url, json=metadata_payload(data, filename=filename, description="Новый текст")
    )
    assert response.status_code == 422
    assert (folder / "INDEX.md").read_bytes() == b""
    assert (folder / "bounce/1.mp3").read_bytes() == b"0123456789"


@pytest.mark.parametrize("change", ["modify", "replace", "delete", "rename", "symlink"])
def test_external_audio_change_rejects_all_updates(
    rename_editor: RenameEditor, change: str
) -> None:
    """Отклоняет общую запись, если аудиофайл изменили или подменили после открытия формы."""
    folder, client, url, data = rename_editor
    original = folder / "bounce/1.mp3"
    before = client.get("/api/state").json()
    if change == "modify":
        original.write_bytes(b"changed audio")
    elif change == "replace":
        info = original.stat()
        replacement = folder / "bounce/replacement"
        replacement.write_bytes(original.read_bytes())
        os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
        replacement.replace(original)
    elif change == "delete":
        original.unlink()
    elif change == "rename":
        original.rename(folder / "bounce/Внешнее имя.mp3")
    else:
        original.unlink()
        original.symlink_to(folder / "bounce/2.mp3")
    response = client.put(
        url, json=metadata_payload(data, filename="Моё имя", description="Новый текст")
    )
    assert response.status_code == 409
    assert not (folder / "bounce/Моё имя.mp3").exists()
    assert (folder / "INDEX.md").read_bytes() == b""
    assert client.get("/api/state").json() == before


def test_index_conflict_prevents_rename(rename_editor: RenameEditor) -> None:
    """Сохраняет исходное имя при внешнем изменении индекса."""
    folder, client, url, data = rename_editor
    external = "Изменено извне\n"
    (folder / "INDEX.md").write_text(external, encoding="utf-8")
    response = client.put(url, json=metadata_payload(data, filename="Новое имя"))
    assert response.status_code == 409
    assert (folder / "bounce/1.mp3").exists()
    assert not (folder / "bounce/Новое имя.mp3").exists()
    assert (folder / "INDEX.md").read_text(encoding="utf-8") == external


def test_index_write_failure_rolls_back_rename(rename_editor: RenameEditor) -> None:
    """Возвращает исходное имя при ошибке индекса и позволяет повторить тот же запрос."""
    folder, client, url, data = rename_editor
    before = client.get("/api/state").json()
    update = metadata_payload(
        data, filename="Новое имя", description="Новый текст", tags={"rating": 8}
    )
    with patch("web_player.metadata.Path.replace", side_effect=PermissionError):
        response = client.put(url, json=update)
    assert response.status_code == 500
    assert (folder / "bounce/1.mp3").read_bytes() == b"0123456789"
    assert not (folder / "bounce/Новое имя.mp3").exists()
    assert (folder / "INDEX.md").read_bytes() == b""
    assert client.get("/api/state").json() == before
    assert client.get(url).json() == data
    assert list((folder / "bounce").glob(".rename-*")) == []
    assert list(folder.glob(".INDEX-*")) == []
    assert client.put(url, json=update).status_code == 200


def test_rename_failure_does_not_write_index(rename_editor: RenameEditor) -> None:
    """Оставляет индекс и исходное аудио при ошибке файловой операции переименования."""
    folder, client, url, data = rename_editor

    def fail_source_unlink(path: Path, backup: Path) -> None:
        """Отклоняет удаление исходного имени, разрешая очистку нового пути."""
        if path == folder / "bounce/1.mp3":
            raise PermissionError
        remove_audio_link(path, backup)

    with patch("web_player.renaming.remove_audio_link", side_effect=fail_source_unlink):
        response = client.put(
            url, json=metadata_payload(data, filename="Новое имя", description="Новый текст")
        )
    assert response.status_code == 500
    assert (folder / "bounce/1.mp3").read_bytes() == b"0123456789"
    assert not (folder / "bounce/Новое имя.mp3").exists()
    assert (folder / "INDEX.md").read_bytes() == b""


def test_rename_never_overwrites_racing_destination(rename_editor: RenameEditor) -> None:
    """Не перезаписывает файл, появившийся после предварительной проверки нового имени."""
    folder, client, url, data = rename_editor
    target = folder / "bounce/Занято.mp3"

    def raced_link(source: Path, destination: Path) -> None:
        """Создаёт занятый путь непосредственно перед попыткой переименования."""
        if destination == target:
            target.write_bytes(b"other audio")
        link_audio(source, destination)

    with patch("web_player.renaming.link_audio", side_effect=raced_link):
        response = client.put(
            url, json=metadata_payload(data, filename="Занято", description="Правки")
        )
    assert response.status_code == 409
    assert target.read_bytes() == b"other audio"
    assert (folder / "bounce/1.mp3").read_bytes() == b"0123456789"
    assert (folder / "INDEX.md").read_bytes() == b""


def test_failed_rollback_keeps_audio_backup(rename_editor: RenameEditor) -> None:
    """Не удаляет резервную копию аудио при дополнительной ошибке восстановления имени."""
    folder, client, url, data = rename_editor
    original = folder / "bounce/1.mp3"

    def fail_restore(source: Path, target: Path) -> None:
        """Отклоняет восстановление прежнего имени после ошибки записи индекса."""
        if target == original:
            raise PermissionError
        link_audio(source, target)

    with (
        patch("web_player.metadata.Path.replace", side_effect=PermissionError),
        patch("web_player.renaming.link_audio", side_effect=fail_restore),
    ):
        response = client.put(url, json=metadata_payload(data, filename="Новое имя"))
    assert response.status_code == 500
    backup = next((folder / "bounce").glob(".rename-*/1.mp3"))
    assert backup.read_bytes() == b"0123456789"
    assert str(backup) in response.json()["detail"]
    assert (folder / "bounce/Новое имя.mp3").read_bytes() == b"0123456789"
    assert (folder / "INDEX.md").read_bytes() == b""


@pytest.mark.parametrize("fail", [False, True])
def test_case_only_rename_and_rollback(rename_editor: RenameEditor, fail: bool) -> None:
    """Поддерживает смену регистра имени и возврат исходного написания при ошибке записи."""
    folder, client, url, data = rename_editor
    assert client.put(url, json=metadata_payload(data, filename="Song")).status_code == 200
    data = client.get(url).json()
    if fail:
        with patch("web_player.metadata.Path.replace", side_effect=PermissionError):
            response = client.put(url, json=metadata_payload(data, filename="song"))
        assert response.status_code == 500
    else:
        assert client.put(url, json=metadata_payload(data, filename="song")).status_code == 200
    names = {item.name for item in (folder / "bounce").iterdir()}
    assert ("Song.mp3" in names) is fail
    assert ("song.mp3" in names) is not fail


def test_second_editor_cannot_rename_changed_track(rename_editor: RenameEditor) -> None:
    """Обнаруживает устаревшее имя файла даже при неизменном содержимом индекса."""
    folder, client, url, data = rename_editor
    assert client.put(url, json=metadata_payload(data, filename="Первое имя")).status_code == 200
    response = client.put(url, json=metadata_payload(data, filename="Второе имя"))
    assert response.status_code == 409
    assert (folder / "bounce/Первое имя.mp3").exists()
    assert not (folder / "bounce/Второе имя.mp3").exists()


def test_index_conflict_during_rename_restores_name(rename_editor: RenameEditor) -> None:
    """Возвращает имя при конфликте индекса между переименованием и записью описания."""
    folder, client, url, data = rename_editor

    def change_index(source: Path, target: Path) -> Iterator[None]:
        """Подменяет индекс после изменения имени и перед финальной проверкой версии."""
        with renamed_audio(source, target):
            (folder / "INDEX.md").write_text("Внешние правки", encoding="utf-8")
            yield

    with patch("web_player.metadata.renamed_audio", side_effect=contextmanager(change_index)):
        response = client.put(url, json=metadata_payload(data, filename="Новое имя"))
    assert response.status_code == 409
    assert (folder / "INDEX.md").read_text(encoding="utf-8") == "Внешние правки"
    assert (folder / "bounce/1.mp3").exists()
    assert not (folder / "bounce/Новое имя.mp3").exists()
