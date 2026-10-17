"""Данные треков и единой очереди плеера."""

import random
from pathlib import Path

from pydantic import BaseModel, Field


class Track(BaseModel):
    """Описывает музыкальный файл и его отображаемые сведения."""

    id: str
    name: str
    directory: str
    path: Path = Field(exclude=True)


class QueueView(BaseModel):
    """Представляет текущий трек и доступный фрагмент очереди."""

    current: Track | None
    previous: list[Track]
    upcoming: list[Track]
    total: int
    total_directories: int
    has_previous: bool
    has_next: bool
    has_next_directory: bool
    shuffled: bool
    ended: bool
    current_index: int | None
    playlist_total: int
    playlist_revision: int


class PlaylistPage(BaseModel):
    """Представляет страницу единого плейлиста в порядке воспроизведения."""

    tracks: list[Track]
    offset: int
    total: int
    revision: int


class PlayerQueue(BaseModel):
    """Управляет общей очередью и историей переходов между треками."""

    tracks: dict[str, Track]
    total_directories: int = 0
    current_id: str | None = None
    history: list[str] = Field(default_factory=list)
    remaining: list[str] = Field(default_factory=list)
    ended: bool = False
    shuffled: bool = False
    order: list[str] = Field(default_factory=list)
    playlist_revision: int = 0

    def playlist_page(self, offset: int, limit: int = 100) -> PlaylistPage:
        """Возвращает порцию плейлиста, включая ранее проигранные и пропущенные файлы."""
        return PlaylistPage(
            tracks=[self.tracks[key] for key in self.order[offset : offset + limit]],
            offset=offset,
            total=len(self.order),
            revision=self.playlist_revision,
        )

    def _next_directory_index(self) -> int | None:
        """Находит первый будущий файл другой директории в обычном режиме."""
        if self.shuffled or self.current_id is None:
            return None
        directory = self.tracks[self.current_id].directory
        return next(
            (i for i, key in enumerate(self.remaining) if self.tracks[key].directory != directory),
            None,
        )

    def view(self) -> QueueView:
        """Возвращает текущий трек, историю и положение в едином плейлисте."""
        return QueueView(
            current=self.tracks.get(self.current_id) if self.current_id else None,
            previous=[self.tracks[key] for key in self.history],
            upcoming=[self.tracks[key] for key in self.remaining[:100]],
            total=len(self.tracks),
            total_directories=self.total_directories,
            has_previous=bool(self.history),
            has_next=bool(self.remaining),
            has_next_directory=self._next_directory_index() is not None,
            shuffled=self.shuffled,
            ended=self.ended,
            current_index=self.order.index(self.current_id) if self.current_id else None,
            playlist_total=len(self.order),
            playlist_revision=self.playlist_revision,
        )

    def next(self) -> QueueView:
        """Переключает очередь вперёд или отмечает окончание воспроизведения."""
        if self.remaining:
            if self.current_id:
                self.history.append(self.current_id)
            self.current_id = self.remaining.pop(0)
            self.ended = False
        else:
            self.ended = True
        return self.view()

    def previous(self) -> QueueView:
        """Возвращает предыдущий трек в начало будущей очереди."""
        if self.history:
            if self.current_id:
                self.remaining.insert(0, self.current_id)
            self.current_id = self.history.pop()
            self.ended = False
        return self.view()

    def shuffle(self) -> QueueView:
        """Перемешивает оставшуюся очередь, сохраняя текущий трек и историю."""
        if self.remaining:
            random.shuffle(self.remaining)
            remaining = set(self.remaining)
            shuffled = iter(self.remaining)
            self.order = [next(shuffled) if key in remaining else key for key in self.order]
            self.playlist_revision += 1
            self.shuffled = True
        return self.view()

    def next_directory(self) -> QueueView:
        """Пропускает остаток директории без добавления пропущенных файлов в историю."""
        index = self._next_directory_index()
        if index is not None:
            del self.remaining[:index]
            return self.next()
        return self.view()

    def select(self, track_id: str) -> QueueView:
        """Выбирает трек из будущей очереди или возвращается к нему по истории."""
        if track_id == self.current_id:
            self.ended = False
        elif track_id in self.remaining:
            del self.remaining[: self.remaining.index(track_id)]
            return self.next()
        elif track_id in self.history:
            index = len(self.history) - 1 - self.history[::-1].index(track_id)
            self.remaining = (
                self.history[index + 1 :]
                + ([self.current_id] if self.current_id else [])
                + self.remaining
            )
            self.history = self.history[:index]
            self.current_id = track_id
            self.ended = False
        elif track_id in self.order:
            if self.current_id:
                self.history.append(self.current_id)
            self.current_id = track_id
            self.remaining = self.order[self.order.index(track_id) + 1 :]
            self.ended = False
        else:
            raise ValueError("Трек отсутствует в очереди")
        return self.view()
