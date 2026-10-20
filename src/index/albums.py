"""Загружает и проверяет конфигурацию музыкальных альбомов."""

import tomllib
from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Self

from pydantic import BaseModel, ConfigDict, StrictInt, computed_field, model_validator

from .resources import ALBUM_CONFIG_PATH


class Album(BaseModel):
    """Описывает альбом, доступный в селекторе альбомных тегов."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    year: StrictInt | None = None
    genre: str | None = None

    @computed_field
    @property
    def display_name(self) -> str:
        """Возвращает имя альбома с годом или пометкой TBA."""
        return f"{self.name} ({self.year if self.year is not None else 'TBA'})"

    @model_validator(mode="after")
    def validate_album(self) -> Self:
        """Проверяет обязательное имя и допустимый жанр альбома."""
        if not self.id.strip() or "\n" in self.id or "\r" in self.id:
            raise ValueError("ID альбома должен быть непустой строкой в одну строку")
        if not self.name.strip() or "\n" in self.name or "\r" in self.name:
            raise ValueError(f"Имя альбома {self.id!r} должно быть непустой строкой в одну строку")
        if self.genre is not None:
            from .tags import get_tag_definitions

            genre_definition = get_tag_definitions().get("genre")
            if genre_definition is None or genre_definition.type != "single_choice":
                raise ValueError(
                    "Для проверки жанра альбома нужен тег [tag.genre] типа single_choice"
                )
            if self.genre not in (genre_definition.choices or ()):
                raise ValueError(f"Недопустимый жанр альбома {self.id!r}: {self.genre!r}")
        return self


def parse_album_config(text: str) -> Mapping[str, Album]:
    """Разбирает конфиг альбомов и проверяет уникальность их имён."""
    data = tomllib.loads(text)
    unknown_sections = set(data) - {"album"}
    if unknown_sections:
        raise ValueError(f"Неизвестные секции конфига альбомов: {sorted(unknown_sections)!r}")
    album_sections = data.get("album")
    if not isinstance(album_sections, dict) or not album_sections:
        raise ValueError("В конфиге должна быть непустая секция [album.<id>]")
    if any(not key.strip() for key in album_sections):
        raise ValueError("ID альбомов в конфиге не должны быть пустыми")
    albums: dict[str, Album] = {}
    for key, value in album_sections.items():
        if not isinstance(value, dict) or "id" in value:
            raise ValueError(
                f"Секция альбома {key!r} должна содержать только поля name, year и genre"
            )
        albums[key] = Album.model_validate({"id": key, **value})
    names = [album.name for album in albums.values()]
    if len(names) != len(set(names)):
        raise ValueError("Имена альбомов в конфиге должны быть уникальными")
    return MappingProxyType(albums)


@lru_cache(maxsize=1)
def get_albums() -> Mapping[str, Album]:
    """Читает конфиг альбомов один раз за время работы процесса."""
    return parse_album_config(ALBUM_CONFIG_PATH.read_text(encoding="utf-8"))
