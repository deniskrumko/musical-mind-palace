"""Проверки библиотеки, общей очереди и выдачи аудио веб-плеером."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.utils import local_ip
from index import Index
from web_player.app import create_app
from web_player.library import scan_library


def make_song(root: Path, name: str, files: tuple[str, ...]) -> Path:
    """Создаёт музыкальную директорию с указанными файлами категорий."""
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "INDEX.md").write_text("", encoding="utf-8")
    for name in files:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0123456789")
    return folder


def metadata_payload(data: dict, **changes: object) -> dict:
    """Собирает запрос сохранения редактора с версиями индекса и аудиофайла."""
    return {
        key: changes.get(key, data[key])
        for key in ("revision", "file_revision", "filename", "description", "tags")
    }


def test_library_order_and_metadata(tmp_path):
    """Сохраняет порядок директорий и all_music_files вместо общей сортировки."""
    make_song(tmp_path, "Б", ("bounce/а.wav",))
    make_song(tmp_path, "А", ("dict/я.m4a", "dict/б.mp4", "bounce/а.mp3", "other.txt"))
    make_song(tmp_path, "Пустая", ())
    queue = scan_library(tmp_path)
    assert [track.name for track in queue.tracks.values()] == ["б.mp4", "я.m4a", "а.mp3", "а.wav"]
    assert queue.view().current.directory == "А"
    assert queue.view().total_directories == 3
    assert queue.view().total == 4
    assert "path" not in queue.view().model_dump()["current"]
    assert list(scan_library(tmp_path).tracks) == list(queue.tracks)


def test_shared_queue_shuffle_history_and_end(tmp_path):
    """Сохраняет историю и текущий трек при перемешивании будущей очереди."""
    make_song(tmp_path, "Песня", tuple(f"bounce/{number:03}.mp3" for number in range(115)))
    app = create_app(tmp_path)
    with TestClient(app) as client, TestClient(create_app(tmp_path)) as independent:
        assert len(client.get("/api/state").json()["upcoming"]) == 100
        for _ in range(12):
            before = client.post("/api/next").json()
        assert len(before["previous"]) == 12
        with patch(
            "web_player.resources.random.shuffle", side_effect=lambda items: items.reverse()
        ):
            shuffled = client.post("/api/shuffle").json()
        assert shuffled["current"] == before["current"]
        assert shuffled["previous"] == before["previous"]
        assert shuffled["upcoming"][0]["name"] == "114.mp3"
        assert independent.get("/api/state").json()["current"]["name"] == "000.mp3"
        second = TestClient(app)
        try:
            assert second.get("/api/state").json() == shuffled
        finally:
            second.close()


def test_queue_navigation_and_single_state(tmp_path):
    """Делит очередь между запросами и останавливается после последнего трека."""
    make_song(tmp_path, "Песня", ("bounce/а.mp3", "bounce/б.wav"))
    app = create_app(tmp_path)
    with TestClient(app) as client:
        first = client.get("/api/state").json()
        second = client.post("/api/next").json()
        assert second["previous"] == [first["current"]]
        assert client.get("/api/state").json() == second
        ended = client.post("/api/next").json()
        assert ended["ended"] is True
        assert ended["current"] == second["current"]
        back = client.post("/api/previous").json()
        assert back["current"] == first["current"]
        assert back["upcoming"] == [second["current"]]
        assert back["ended"] is False


def test_audio_range_and_missing_files(tmp_path):
    """Поддерживает перемотку и отклоняет неизвестные, удалённые и подменённые файлы."""
    folder = make_song(tmp_path, "Песня", ("bounce/трек.mp3",))
    with TestClient(create_app(tmp_path)) as client:
        track = client.get("/api/state").json()["current"]
        url = f"/audio/{track['id']}"
        response = client.get(url, headers={"Range": "bytes=2-5"})
        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-range"] == "bytes 2-5/10"
        assert response.headers["content-type"].startswith("audio/mpeg")
        assert client.get("/audio/unknown").status_code == 404
        assert client.get("/audio/../../etc/passwd").status_code == 404
        path = folder / "bounce/трек.mp3"
        path.unlink()
        assert client.get(url).status_code == 404
        path.symlink_to(tmp_path / "INDEX.md")
        assert client.get(url).status_code == 404


def test_empty_library_and_page(tmp_path):
    """Отдаёт страницу, статику и корректное состояние пустой библиотеки."""
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Музыкальный плеер" in response.text
        assert client.get("/static/js/player.js").status_code == 200
        assert client.get("/static/css/player.css").status_code == 200
        view = client.get("/api/state").json()
        assert view["current"] is None
        assert view["total"] == 0
        assert view["total_directories"] == 0
        assert client.post("/api/shuffle").json() == view
        assert client.post("/api/previous").json() == view
        assert client.post("/api/next").json()["ended"] is True


def test_reveal_track_in_finder(tmp_path: Path) -> None:
    """Выделяет выбранный файл в Finder без изменения очереди и воспроизведения."""
    folder = make_song(tmp_path, "Песня с пробелами", ("bounce/трек.mp3", "bounce/ещё.mp3"))
    with (
        TestClient(create_app(tmp_path)) as client,
        patch("web_player.app.sys.platform", "darwin"),
        patch("web_player.app.subprocess.run") as run,
    ):
        track = client.get("/api/state").json()["current"]
        state = client.post("/api/next").json()
        response = client.post(f"/api/reveal/{track['id']}")
        assert response.status_code == 204
        assert response.content == b""
        run.assert_called_once_with(
            ["/usr/bin/open", "-R", str(folder / "bounce" / track["name"])], check=True, timeout=5
        )
        assert client.get("/api/state").json() == state


def test_reveal_rejects_unavailable_files(tmp_path: Path) -> None:
    """Отклоняет неизвестные, удалённые и подменённые файлы без запуска Finder."""
    folder = make_song(tmp_path / "library", "Песня", ("bounce/трек.mp3",))
    with (
        TestClient(create_app(tmp_path / "library")) as client,
        patch("web_player.app.sys.platform", "darwin"),
        patch("web_player.app.subprocess.run") as run,
    ):
        track = client.get("/api/state").json()["current"]
        url = f"/api/reveal/{track['id']}"
        assert client.post("/api/reveal/unknown").status_code == 404
        path = folder / "bounce/трек.mp3"
        path.unlink()
        assert client.post(url).status_code == 404
        outside = tmp_path / "outside.mp3"
        outside.write_bytes(b"audio")
        path.symlink_to(outside)
        assert client.post(url).status_code == 404
        run.assert_not_called()


def test_reveal_platform_and_launch_errors(tmp_path: Path) -> None:
    """Сообщает об отсутствии macOS и ошибках запуска Finder."""
    make_song(tmp_path, "Песня", ("bounce/трек.mp3",))
    with TestClient(create_app(tmp_path)) as client, patch("web_player.app.subprocess.run") as run:
        track = client.get("/api/state").json()["current"]
        url = f"/api/reveal/{track['id']}"
        with patch("web_player.app.sys.platform", "linux"):
            assert client.post(url).status_code == 501
        run.assert_not_called()
        with patch("web_player.app.sys.platform", "darwin"):
            for error in (
                OSError(),
                subprocess.CalledProcessError(1, "open"),
                subprocess.TimeoutExpired("open", 5),
            ):
                run.side_effect = error
                response = client.post(url)
                assert response.status_code == 500
                assert response.json()["detail"] == "Не удалось открыть файл в Finder"


def test_network_address():
    """Получает IPv4 интерфейса, выбранного системой для UDP-соединения."""
    with patch("core.utils.socket.socket") as socket_factory:
        connection = socket_factory.return_value
        connection.getsockname.return_value = ("192.168.1.5", 12345)
        assert local_ip() == "192.168.1.5"
        connection.connect.assert_called_once_with(("8.8.8.8", 80))
        connection.close.assert_called_once_with()


def test_next_directory_skips_files_and_preserves_history(tmp_path):
    """Пропускает остаток директории и возвращает назад только прослушанный файл."""
    make_song(tmp_path, "А", ("dict/1.m4a", "bounce/2.mp3", "bounce/3.wav"))
    make_song(tmp_path, "Б", ("dict/4.m4a", "bounce/5.mp3"))
    with TestClient(create_app(tmp_path)) as client:
        first = client.get("/api/state").json()
        assert first["has_next_directory"] is True
        assert first["has_previous_directory"] is False
        jumped = client.post("/api/next-directory").json()
        assert jumped["current"]["directory"] == "Б"
        assert jumped["current"]["name"] == "4.m4a"
        assert jumped["previous"] == [first["current"]]
        assert [track["name"] for track in jumped["upcoming"]] == ["5.mp3"]
        assert jumped["has_next_directory"] is False
        assert jumped["has_previous_directory"] is True
        back_directory = client.post("/api/previous-directory").json()
        assert back_directory["current"] == first["current"]
        assert [track["name"] for track in back_directory["upcoming"]] == ["4.m4a", "5.mp3"]
        jumped = client.post("/api/next-directory").json()
        assert client.post("/api/next-directory").json() == jumped
        back = client.post("/api/previous").json()
        assert back["current"] == first["current"]
        assert [track["name"] for track in back["upcoming"]] == ["4.m4a", "5.mp3"]
        assert client.post("/api/next").json()["current"] == jumped["current"]


def test_next_directory_beyond_playlist_window(tmp_path):
    """Находит границу директории даже за пределами ста видимых будущих файлов."""
    make_song(tmp_path, "А", tuple(f"bounce/{i:03}.mp3" for i in range(105)))
    make_song(tmp_path, "Б", ("bounce/песня.mp3",))
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/state").json()["has_next_directory"] is True
        assert client.post("/api/next-directory").json()["current"]["directory"] == "Б"


def test_shuffle_disables_directory_navigation_until_restart(tmp_path):
    """Отключает переход директорий после shuffle даже при неизменившемся порядке."""
    make_song(tmp_path, "А", ("bounce/1.mp3", "bounce/2.mp3"))
    make_song(tmp_path, "Б", ("bounce/3.mp3",))
    with TestClient(create_app(tmp_path)) as client:
        with patch("web_player.resources.random.shuffle"):
            shuffled = client.post("/api/shuffle").json()
        assert shuffled["shuffled"] is True
        assert shuffled["has_next_directory"] is False
        assert client.post("/api/next-directory").json() == shuffled
        assert client.post("/api/next").json()["current"]["name"] == "2.mp3"
        assert client.post("/api/previous").json()["shuffled"] is True
    with TestClient(create_app(tmp_path)) as restarted:
        view = restarted.get("/api/state").json()
        assert view["shuffled"] is False
        assert view["has_next_directory"] is True


def test_frontend_media_controls_and_grouping():
    """Проверяет системные кнопки, переход директорий и группировку JS без браузера."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Для проверки JavaScript необходим Node.js")
    subprocess.run([node, str(Path(__file__).parent / "js" / "web_player.cjs")], check=True)


def test_select_upcoming_and_history(tmp_path):
    """Выбирает будущий файл без ложной истории и возвращает прослушанные в очередь."""
    make_song(tmp_path, "Песня", tuple(f"bounce/{i}.mp3" for i in range(5)))
    with TestClient(create_app(tmp_path)) as client:
        initial = client.get("/api/state").json()
        first = initial["current"]
        skipped, selected, fourth, fifth = initial["upcoming"]
        jumped = client.post(f"/api/select/{selected['id']}").json()
        assert jumped["current"] == selected
        assert jumped["previous"] == [first]
        assert jumped["upcoming"] == [fourth, fifth]
        client.post("/api/next")
        back = client.post(f"/api/select/{first['id']}").json()
        assert back["current"] == first
        assert back["previous"] == []
        assert back["upcoming"] == [selected, fourth, fifth]
        assert client.post("/api/select/unknown").status_code == 404
        assert client.get("/api/state").json() == back
        assert client.post(f"/api/select/{skipped['id']}").json()["current"] == skipped


def test_select_after_shuffle_and_end(tmp_path):
    """Сохраняет режим shuffle при выборе файла и позволяет повторить последний."""
    make_song(tmp_path, "Песня", tuple(f"bounce/{i}.mp3" for i in range(3)))
    with TestClient(create_app(tmp_path)) as client:
        shuffled = client.post("/api/shuffle").json()
        last = shuffled["upcoming"][-1]
        selected = client.post(f"/api/select/{last['id']}").json()
        assert selected["current"] == last
        assert selected["shuffled"] is True
        assert selected["upcoming"] == []
        assert client.post("/api/next").json()["ended"] is True
        resumed = client.post(f"/api/select/{last['id']}").json()
        assert resumed["current"] == last
        assert resumed["ended"] is False


def test_playlist_pages_retain_played_tracks(tmp_path):
    """Подгружает все файлы порциями и сохраняет порядок после переходов вперёд и назад."""
    make_song(tmp_path, "Песня", tuple(f"bounce/{i:03}.mp3" for i in range(205)))
    with TestClient(create_app(tmp_path)) as client:
        pages = [client.get(f"/api/playlist?offset={offset}").json() for offset in (0, 100, 200)]
        assert [len(page["tracks"]) for page in pages] == [100, 100, 5]
        all_tracks = [track for page in pages for track in page["tracks"]]
        assert len({track["id"] for track in all_tracks}) == 205
        for _ in range(15):
            state = client.post("/api/next").json()
        assert state["current_index"] == 15
        assert len(state["previous"]) == 15
        assert client.get("/api/playlist?offset=0").json() == pages[0]
        assert client.post("/api/previous").json()["current_index"] == 14
        assert client.get("/api/playlist?offset=100").json() == pages[1]
        assert client.get("/api/playlist?offset=205").json()["tracks"] == []
        assert client.get("/api/playlist?offset=-1").status_code == 422


def test_playlist_shuffle_and_skipped_tracks(tmp_path):
    """Сохраняет пропущенные и прослушанные строки, обновляя только порядок будущих."""
    make_song(tmp_path, "А", ("bounce/1.mp3", "bounce/2.mp3"))
    make_song(tmp_path, "Б", ("bounce/3.mp3", "bounce/4.mp3", "bounce/5.mp3"))
    with TestClient(create_app(tmp_path)) as client:
        before = client.get("/api/playlist").json()
        jumped = client.post("/api/next-directory").json()
        assert jumped["current_index"] == 2
        assert client.get("/api/playlist").json() == before
        with patch(
            "web_player.resources.random.shuffle", side_effect=lambda items: items.reverse()
        ):
            client.post("/api/shuffle")
        after = client.get("/api/playlist").json()
        assert after["tracks"][:3] == before["tracks"][:3]
        assert after["tracks"][3:] == before["tracks"][3:][::-1]
        assert after["revision"] == before["revision"] + 1


def test_metadata_editor_saves_all_types_and_updates_directory(tmp_path: Path) -> None:
    """Сохраняет все типы тегов в общем индексе и обновляет только его треки."""
    folder = make_song(tmp_path, "А", ("dict/1.m4a", "bounce/2.mp3"))
    make_song(tmp_path, "Б", ("bounce/3.mp3",))
    path = folder / "INDEX.md"
    original = "# Песня\n\nОписание и https://example.com\n\n## Rating\n3\n"
    path.write_text(original, encoding="utf-8")
    with TestClient(create_app(tmp_path)) as client:
        before = client.get("/api/state").json()
        track_id = before["current"]["id"]
        url = f"/api/metadata/{track_id}"
        data = client.get(url).json()
        assert data["description"] == Index.parse(original).description
        assert data["tags"] == {"rating": 3}
        assert list(data["definitions"]) == [
            "original_folder",
            "other_names",
            "album",
            "genre",
            "specialty",
            "sounds_like",
            "lyrics",
            "has_vocals",
            "state",
            "mood",
            "speed",
            "rating",
        ]
        assert data["definitions"]["genre"]["display_name"] == "Жанр"
        assert data["definitions"]["genre"]["choices"] == ["acoustic", "heavy", "piano", "polystra"]
        tags = {
            "original_folder": "Архив/Песня",
            "other_names": ["Песня", "Song"],
            "genre": "piano",
            "lyrics": "\nПервый куплет\n\n### Припев\nТекст",
            "has_vocals": True,
            "mood": ["sad", "kind"],
            "rating": 10,
        }
        response = client.put(
            url,
            json=metadata_payload(data, description="# Новое имя\n\nОписание", tags=tags),
        )
        assert response.status_code == 200
        saved = response.json()
        assert saved["revision"] != data["revision"]
        index = Index.load(path)
        assert {key: tag.value for key, tag in index.tags.items()} == tags
        assert saved["description"] == index.description
        assert client.get(url).json() == saved
        state = client.get("/api/state").json()
        assert state["current"]["id"] == track_id
        assert state["previous"] == before["previous"]
        assert [track["id"] for track in state["upcoming"]] == [
            track["id"] for track in before["upcoming"]
        ]
        tracks = client.get("/api/playlist").json()["tracks"]
        assert tracks[0]["tags"] == tracks[1]["tags"] == state["current"]["tags"]
        assert tracks[2]["tags"] == []
        cleared = client.put(url, json=metadata_payload(saved, description="", tags={}))
        assert cleared.status_code == 200
        assert path.read_text(encoding="utf-8") == ""
        assert client.get("/api/state").json()["current"]["tags"] == []


@pytest.mark.parametrize("change", ["modify", "delete", "create"])
def test_metadata_conflict_preserves_disk_and_memory(tmp_path: Path, change: str) -> None:
    """Отклоняет сохранение поверх изменённого, удалённого или созданного индекса."""
    path = make_song(tmp_path, "Песня", ("bounce/1.mp3",)) / "INDEX.md"
    with TestClient(create_app(tmp_path)) as client:
        if change == "create":
            path.unlink()
        before = client.get("/api/state").json()
        url = f"/api/metadata/{before['current']['id']}"
        data = client.get(url).json()
        if change == "delete":
            path.unlink()
            expected = None
        else:
            expected = "# Изменено извне\r\n".encode()
            path.write_bytes(expected)
        response = client.put(
            url,
            json=metadata_payload(data, description="Мои правки", tags={"rating": 8}),
        )
        assert response.status_code == 409
        assert (path.read_bytes() if path.exists() else None) == expected
        assert client.get("/api/state").json() == before


@pytest.mark.parametrize(
    "description,tags",
    [
        ("Описание", {"rating": 11}),
        ("Описание", {"rating": True}),
        ("Описание", {"rating": 2.5}),
        ("Описание", {"genre": "unknown"}),
        ("Описание", {"mood": ["unknown"]}),
        ("Описание", {"other_names": ["Строка\nЕщё строка"]}),
        ("Описание", {"unknown": "значение"}),
        ("Описание", {"lyrics": ""}),
        ("## Rating\n8", {}),
        ("Описание", {"lyrics": "Куплет\n## Rating\n8"}),
    ],
)
def test_metadata_rejects_invalid_values_without_writing(
    tmp_path: Path, description: str, tags: dict
) -> None:
    """Отклоняет неверные типы и текст, меняющий структуру индекса при чтении."""
    path = make_song(tmp_path, "Песня", ("bounce/1.mp3",)) / "INDEX.md"
    with TestClient(create_app(tmp_path)) as client:
        before = client.get("/api/state").json()
        url = f"/api/metadata/{before['current']['id']}"
        data = client.get(url).json()
        response = client.put(url, json=metadata_payload(data, description=description, tags=tags))
        assert response.status_code == 422
        assert path.read_bytes() == b""
        assert client.get("/api/state").json() == before


def test_metadata_write_failure_preserves_index(tmp_path: Path) -> None:
    """Сохраняет прежний индекс и сведения при ошибке атомарной замены файла."""
    folder = make_song(tmp_path, "Песня", ("bounce/1.mp3",))
    with TestClient(create_app(tmp_path)) as client:
        before = client.get("/api/state").json()
        url = f"/api/metadata/{before['current']['id']}"
        data = client.get(url).json()
        with patch("web_player.metadata.Path.replace", side_effect=PermissionError):
            response = client.put(
                url,
                json=metadata_payload(data, description="Новое описание", tags={}),
            )
        assert response.status_code == 500
        assert (folder / "INDEX.md").read_bytes() == b""
        assert list(folder.glob(".INDEX-*")) == []
        assert client.get("/api/state").json() == before


def test_metadata_rejects_unknown_tracks_and_symlinks(tmp_path: Path) -> None:
    """Не читает и не перезаписывает подменённый ссылкой индекс или чужой файл."""
    folder = make_song(tmp_path / "library", "Песня", ("bounce/1.mp3",))
    path = folder / "INDEX.md"
    outside = tmp_path / "outside.md"
    outside.write_text("Сохранить", encoding="utf-8")
    with TestClient(create_app(tmp_path / "library")) as client:
        track = client.get("/api/state").json()["current"]
        url = f"/api/metadata/{track['id']}"
        data = client.get(url).json()
        update = metadata_payload(data, description="Новое описание", tags={})
        assert client.get("/api/metadata/unknown").status_code == 404
        assert client.put("/api/metadata/unknown", json=update).status_code == 404
        path.unlink()
        path.symlink_to(outside)
        assert client.get(url).status_code == 400
        assert client.put(url, json=update).status_code == 422
        assert outside.read_text(encoding="utf-8") == "Сохранить"
