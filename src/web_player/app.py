"""HTTP-интерфейс музыкального плеера и потоковая выдача аудио."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.logicx import is_file
from web_player.library import scan_library
from web_player.resources import PlaylistPage, QueueView

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

    @app.post("/api/select/{track_id}")
    async def select_track(track_id: str) -> QueueView:
        """Выбирает указанный трек из очереди или истории прослушивания."""
        try:
            return app.state.queue.select(track_id)
        except ValueError as error:
            raise HTTPException(404, str(error))

    @app.get("/audio/{track_id}")
    async def audio(track_id: str) -> FileResponse:
        """Отдаёт известный аудиофайл с поддержкой диапазонов для перемотки."""
        track = app.state.queue.tracks.get(track_id)
        if track is None or not is_file(track.path):
            raise HTTPException(404, "Музыкальный файл не найден")
        resolved = track.path.resolve()
        if not resolved.is_relative_to(root):
            raise HTTPException(404, "Музыкальный файл недоступен")
        return FileResponse(resolved, content_disposition_type="inline")

    return app
