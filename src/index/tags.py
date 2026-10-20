"""Модели и конфигурация тегов музыкальных индексов."""

import tomllib
from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, model_validator

from .albums import get_albums
from .resources import CHOICE_TYPES, LIST_TYPES, TAG_CONFIG_PATH, TagType
from .utils import trim_trailing_blank_lines


class TagDefinition(BaseModel):
    """Описывает имя, тип и допустимые варианты тега из конфигурации."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    display_name: str
    type: TagType
    choices: tuple[str, ...] | None = None

    @model_validator(mode="before")
    @classmethod
    def default_display_name(cls, values: Any) -> Any:
        """Подставляет исходное имя, если display_name не указан."""
        if isinstance(values, dict) and "display_name" not in values:
            values = {**values, "display_name": values.get("name")}
        return values

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        """Проверяет имя и варианты определения тега."""
        if not self.name.strip() or "\n" in self.name or "\r" in self.name:
            raise ValueError("Имя тега должно быть непустой строкой в одну строку")
        if self.type in CHOICE_TYPES:
            if not self.choices:
                raise ValueError(f"Для тега {self.name!r} нужно указать непустой choices")
            if any(not choice.strip() for choice in self.choices):
                raise ValueError(f"Варианты тега {self.name!r} не должны быть пустыми")
            if len(set(self.choices)) != len(self.choices):
                raise ValueError(f"Варианты тега {self.name!r} должны быть уникальными")
        elif self.choices is not None:
            raise ValueError(f"Поле choices допустимо только для тегов выбора: {self.name!r}")
        return self


class Tag(BaseModel):
    """Хранит значение тега и проверяет его по единому конфигу приложения."""

    name: str
    type: TagType
    value: str | list[str] | StrictInt | StrictBool
    display_name: str | None = None
    display_value: list[str] | None = None

    @model_validator(mode="after")
    def validate_against_config(self) -> Self:
        """Проверяет имя, тип и значение тега по конфигурации."""
        definitions = get_tag_definitions()
        definition = find_definition_by_name(self.name, definitions)
        if definition is None:
            raise ValueError(f"Тег не описан в конфигурации: {self.name!r}")
        if self.type != definition.type:
            raise ValueError(
                f"Тип тега {self.name!r} должен быть {definition.type!r}, получен {self.type!r}"
            )
        self.display_name = definition.display_name

        if self.type == "star_rating":
            if not isinstance(self.value, int) or isinstance(self.value, bool):
                raise ValueError(f"Значение тега {self.name!r} должно быть целым числом")
            if not 1 <= self.value <= 10:
                raise ValueError(f"Значение тега {self.name!r} должно быть от 1 до 10")
            return self

        if self.type == "bool":
            if not isinstance(self.value, bool):
                raise ValueError(f"Значение тега {self.name!r} должно быть логическим")
            return self

        if self.type in LIST_TYPES:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"Значение тега {self.name!r} должно быть непустым списком")
            if any(not item.strip() or "\n" in item or "\r" in item for item in self.value):
                raise ValueError(f"Элементы тега {self.name!r} должны быть непустыми строками")
            if self.type == "multi_choice":
                choices = definition.choices or ()
                invalid = [item for item in self.value if item not in choices]
                if invalid:
                    raise ValueError(f"Недопустимые варианты тега {self.name!r}: {invalid!r}")
            elif self.type == "album_selector":
                albums = get_albums()
                invalid = [item for item in self.value if item not in albums]
                if invalid:
                    raise ValueError(f"Альбомы не найдены в config/albums.toml: {invalid!r}")
                self.display_value = [albums[item].display_name for item in self.value]
            return self

        if not isinstance(self.value, str):
            raise ValueError(f"Значение тега {self.name!r} должно быть строкой")
        self.value = trim_trailing_blank_lines(self.value)
        if not self.value.strip():
            raise ValueError(f"Значение тега {self.name!r} не должно быть пустым")
        if self.type in {"string", "single_choice"} and ("\n" in self.value or "\r" in self.value):
            raise ValueError(f"Значение тега {self.name!r} должно занимать одну строку")
        if self.type == "single_choice" and self.value not in (definition.choices or ()):
            raise ValueError(f"Недопустимый вариант тега {self.name!r}: {self.value!r}")
        return self

    def render_value(self) -> str:
        """Возвращает значение тега в формате Markdown."""
        if isinstance(self.value, list):
            return "\n".join(f"- {item}" for item in self.value)
        return str(self.value)


def parse_tag_config(text: str) -> Mapping[str, TagDefinition]:
    """Разбирает TOML-конфиг тегов и проверяет уникальность Markdown-имён."""
    data = tomllib.loads(text)
    unknown_sections = set(data) - {"tag"}
    if unknown_sections:
        raise ValueError(f"Неизвестные секции конфига тегов: {sorted(unknown_sections)!r}")
    tag_sections = data.get("tag")
    if not isinstance(tag_sections, dict) or not tag_sections:
        raise ValueError("В конфиге должна быть непустая секция [tag.<key>]")
    if any(not key.strip() for key in tag_sections):
        raise ValueError("Ключи тегов в конфиге не должны быть пустыми")
    definitions = {key: TagDefinition.model_validate(value) for key, value in tag_sections.items()}
    names = [definition.name for definition in definitions.values()]
    if len(names) != len(set(names)):
        raise ValueError("Имена тегов в конфиге должны быть уникальными")
    return MappingProxyType(definitions)


@lru_cache(maxsize=1)
def get_tag_definitions() -> Mapping[str, TagDefinition]:
    """Читает конфиг тегов один раз за время работы процесса."""
    return parse_tag_config(TAG_CONFIG_PATH.read_text(encoding="utf-8"))


def find_definition_by_name(
    name: str, definitions: Mapping[str, TagDefinition] | None = None
) -> TagDefinition | None:
    """Находит описание тега по заголовку, который записывается в Markdown."""
    definitions = definitions or get_tag_definitions()
    return next((item for item in definitions.values() if item.name == name), None)
