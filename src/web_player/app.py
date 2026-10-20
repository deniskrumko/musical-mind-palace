"""HTTP-интерфейс музыкального плеера и потоковая выдача аудио."""

import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from core.logicx import is_file
from web_player.library import scan_library
from web_player.metadata import load_metadata, save_metadata
from web_player.renaming import MetadataConflictError, RenameRecoveryError
from web_player.resources import MetadataEditor, MetadataUpdate, PlaylistPage, QueueView, Track

STATIC_DIR = Path(__file__).parent / "static"


def create_app(index_dir: Path) -> FastAPI:
    """Создаёт приложение с единой очередью из указанной библиотеки."""
    root = index_dir.expanduser().resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Сканирует библиотеку один раз при запуске приложения."""
        app.state.queue = scan_library(root)
        yield

    app = FastAPI(title="Музыкальные чертоги", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=STATIC_DIR / "templates")

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        """Отрисовывает страницу музыкального плеера."""
        return templates.TemplateResponse(request=request, name="player.html")

    @app.get("/api/state")
    async def state() -> QueueView:
        """Возвращает состояние общей очереди."""
        return app.state.queue.view()

    def metadata_track(track_id: str) -> Track:
        """Находит известный библиотеке трек для редактирования общего индекса."""
        track = app.state.queue.tracks.get(track_id)
        if track is None:
            raise HTTPException(404, "Трек не найден")
        return track

    @app.get("/api/metadata/{track_id}")
    async def metadata(track_id: str) -> MetadataEditor:
        """Возвращает актуальный индекс и поля формы из конфигурации тегов."""
        track = metadata_track(track_id)
        try:
            return load_metadata(root, track)
        except MetadataConflictError as error:
            raise HTTPException(409, str(error))
        except (ValueError, OSError) as error:
            raise HTTPException(400, f"Не удалось прочитать индекс: {error}")

    @app.put("/api/metadata/{track_id}")
    async def update_metadata(track_id: str, update: MetadataUpdate) -> MetadataEditor:
        """Сохраняет имя файла, описание и теги без изменения очереди и воспроизведения."""
        track = metadata_track(track_id)
        try:
            return save_metadata(root, app.state.queue, track, update)
        except MetadataConflictError as error:
            raise HTTPException(409, str(error))
        except ValidationError as error:
            message = error.errors()[0]["msg"].removeprefix("Value error, ")
            raise HTTPException(422, message)
        except ValueError as error:
            raise HTTPException(422, str(error))
        except RenameRecoveryError as error:
            raise HTTPException(500, str(error))
        except OSError as error:
            raise HTTPException(
                500, "Не удалось сохранить имя файла и INDEX.md на диске"
            ) from error

    @app.post("/api/next")
    async def next_track() -> QueueView:
        """Переводит очередь к следующему треку."""
        return app.state.queue.next()

    @app.get("/api/playlist")
    async def playlist(offset: int = Query(default=0, ge=0)) -> PlaylistPage:
        """Отдаёт следующие сто строк плейлиста начиная с указанного смещения."""
        return app.state.queue.playlist_page(offset)

    @app.post("/api/previous")
    async def previous_track() -> QueueView:
        """Переводит очередь к предыдущему прослушанному треку."""
        return app.state.queue.previous()

    @app.post("/api/shuffle")
    async def shuffle() -> QueueView:
        """Перемешивает будущие треки единой очереди."""
        return app.state.queue.shuffle()

    @app.post("/api/next-directory")
    async def next_directory() -> QueueView:
        """Переводит очередь к первому файлу следующей музыкальной директории."""
        return app.state.queue.next_directory()

    @app.post("/api/previous-directory")
    async def previous_directory() -> QueueView:
        """Переводит очередь к первому файлу предыдущей музыкальной директории."""
        return app.state.queue.previous_directory()

    @app.post("/api/select/{track_id}")
    async def select_track(track_id: str) -> QueueView:
        """Выбирает указанный трек из очереди или истории прослушивания."""
        try:
            return app.state.queue.select(track_id)
        except ValueError as error:
            raise HTTPException(404, str(error))

    def audio_path(track_id: str) -> Path:
        """Проверяет существование аудиофайла и его принадлежность библиотеке."""
        track = app.state.queue.tracks.get(track_id)
        if track is None or not is_file(track.path):
            raise HTTPException(404, "Музыкальный файл не найден")
        resolved = track.path.resolve()
        if not resolved.is_relative_to(root):
            raise HTTPException(404, "Музыкальный файл недоступен")
        return resolved

    @app.post("/api/reveal/{track_id}", status_code=204)
    def reveal_track(track_id: str) -> Response:
        """Открывает Finder на компьютере сервера и выделяет указанный аудиофайл."""
        path = audio_path(track_id)
        if sys.platform != "darwin":
            raise HTTPException(501, "Открытие в Finder доступно только на macOS")
        try:
            subprocess.run(["/usr/bin/open", "-R", str(path)], check=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            raise HTTPException(500, "Не удалось открыть файл в Finder") from error
        return Response(status_code=204)

    @app.get("/audio/{track_id}")
    async def audio(track_id: str) -> FileResponse:
        """Отдаёт известный аудиофайл с поддержкой диапазонов для перемотки."""
        return FileResponse(audio_path(track_id), content_disposition_type="inline")

    return app
