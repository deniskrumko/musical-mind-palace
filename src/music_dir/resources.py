"""Представление содержимого музыкальной директории."""

from pathlib import Path
from typing import Self

from pydantic import BaseModel

from core.file_extensions import CATEGORY_EXTENSIONS
from core.logicx import is_directory, is_file
from index import INDEX_FILENAME, Index


class MusicDir(BaseModel):
    """Предоставляет актуальные списки ресурсов музыкальной директории."""

    path: Path
    index: Index | None = None

    @classmethod
    def from_path(cls, path: Path) -> Self:
        """Создаёт представление директории и загружает её индекс."""
        index_path = path / INDEX_FILENAME
        try:
            index = Index.load(index_path)
        except (OSError, ValueError) as error:
            raise ValueError(f"Не удалось загрузить индекс {index_path}: {error}") from error
        return cls(path=path, index=index)

    def _category_files(self, category: str) -> list[Path]:
        """Возвращает файлы поддерживаемых форматов непосредственно из подпапки."""
        folder = self.path / category
        if not is_directory(folder):
            return []
        return sorted(
            entry
            for entry in folder.iterdir()
            if is_file(entry) and entry.suffix.lower() in CATEGORY_EXTENSIONS[category]
        )

    @property
    def all_music_files(self) -> list[Path]:
        """Возвращает музыкальные записи."""
        return self.dict_files + self.bounce_files

    @property
    def dict_files(self) -> list[Path]:
        """Возвращает диктофонные записи из подпапки dict."""
        return self._category_files("dict")

    @property
    def bounce_files(self) -> list[Path]:
        """Возвращает MP3-файлы из подпапки bounce."""
        return self._category_files("bounce")

    @property
    def logic_files(self) -> list[Path]:
        """Возвращает проекты Logic Pro и GarageBand из подпапки logic."""
        return self._category_files("logic")

    @property
    def tab_files(self) -> list[Path]:
        """Возвращает табулатуры из подпапки tab."""
        return self._category_files("tab")

    @property
    def image_files(self) -> list[Path]:
        """Возвращает изображения из подпапки image."""
        return self._category_files("image")

    @property
    def subdirs(self) -> list[Path]:
        """Возвращает обычные подпапки, исключая категории ресурсов."""
        return sorted(
            entry
            for entry in self.path.iterdir()
            if entry.name not in CATEGORY_EXTENSIONS and is_directory(entry)
        )

    @property
    def other_files(self) -> list[Path]:
        """Возвращает файлы корня и проекты Logic Pro и GarageBand, исключая INDEX.md."""
        return sorted(
            entry
            for entry in self.path.iterdir()
            if entry.name != INDEX_FILENAME and is_file(entry)
        )
