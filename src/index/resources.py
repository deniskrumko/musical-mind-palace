"""Чтение, проверка и обновление Markdown-индексов музыкальных папок."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

INDEX_FILENAME = "INDEX.md"
TAG_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tags.toml"
TagType = Literal["string", "text", "list", "single_choice", "multi_choice", "star_rating", "bool"]
CHOICE_TYPES = {"single_choice", "multi_choice"}
LIST_TYPES = {"list", "multi_choice"}


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
    def validate_definition(self) -> TagDefinition:
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

    @model_validator(mode="after")
    def validate_against_config(self) -> Tag:
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


def trim_trailing_blank_lines(value: str) -> str:
    """Удаляет пустые строки только в конце многострочного значения."""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


class Index(BaseModel):
    """Хранит свободное описание и теги, проверенные единым конфигом."""

    description: str = ""
    tags: dict[str, Tag] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tag_keys(self) -> Index:
        """Проверяет соответствие внутренних ключей тегов конфигурации."""
        definitions = get_tag_definitions() if self.tags else {}
        for key, tag in self.tags.items():
            definition = definitions.get(key)
            if definition is None or definition.name != tag.name or definition.type != tag.type:
                raise ValueError(f"Ключ тега не соответствует конфигурации: {key!r}")
        return self

    @classmethod
    def parse(cls, text: str) -> Index:
        """Разбирает индекс и сохраняет описание перед первым тегом."""
        headers = list(re.finditer(r"^##(?!#)[ \t]*([^\r\n]+)", text, re.MULTILINE))
        if not headers:
            return cls(description=text)
        index = cls(description=text[: headers[0].start()])
        definitions = get_tag_definitions()
        keys_by_name = {definition.name: key for key, definition in definitions.items()}
        for position, header in enumerate(headers):
            end = headers[position + 1].start() if position + 1 < len(headers) else len(text)
            name = header.group(1).strip()
            key = keys_by_name.get(name)
            if key is None:
                raise ValueError(f"Тег не описан в конфигурации: {name!r}")
            raw_value = text[header.end() : end]
            if raw_value.startswith("\r\n"):
                value_text = raw_value[2:]
            elif raw_value.startswith(("\n", "\r")):
                value_text = raw_value[1:]
            else:
                value_text = raw_value
            definition = definitions[key]
            if definition.type == "star_rating":
                value: str | list[str] | int | bool = parse_star_rating(name, value_text)
            elif definition.type == "bool":
                value = parse_bool_value(name, value_text)
            elif definition.type in LIST_TYPES:
                value = parse_list_value(name, value_text)
            else:
                value = trim_trailing_blank_lines(value_text)
            index.tags[key] = Tag(name=name, type=definition.type, value=value)
        return index

    @classmethod
    def load(cls, path: Path) -> Index:
        """Читает индекс или возвращает пустой для отсутствующего файла."""
        if path.is_symlink():
            raise ValueError(f"Индекс не должен быть символической ссылкой: {path}")
        return cls.parse(path.read_text(encoding="utf-8")) if path.exists() else cls()

    def set(self, key: str, value: str | list[str] | int | bool) -> None:
        """Записывает значение тега по ключу из конфигурации."""
        definition = get_tag_definitions().get(key)
        if definition is None:
            raise ValueError(f"Ключ тега не описан в конфигурации: {key!r}")
        self.tags[key] = Tag(name=definition.name, type=definition.type, value=value)

    def merge(self, incoming: Index) -> None:
        """Объединяет описания и заменяет теги входящими значениями."""
        if incoming.description:
            if self.description and not self.description.endswith("\n\n"):
                self.description += "\n" if self.description.endswith("\n") else "\n\n"
            self.description += incoming.description
        self.tags.update(incoming.tags)

    def render(self) -> str:
        """Собирает Markdown с заголовками и значениями тегов."""
        result = self.description
        for tag in self.tags.values():
            if result and not result.endswith("\n\n"):
                result += "\n" if result.endswith("\n") else "\n\n"
            result += f"## {tag.name}\n{tag.render_value()}\n"
        return result

    def save(self, path: Path) -> None:
        """Сохраняет индекс в UTF-8 без перехода по символическим ссылкам."""
        if path.is_symlink():
            raise ValueError(f"Индекс не должен быть символической ссылкой: {path}")
        path.write_text(self.render(), encoding="utf-8")


def parse_list_value(name: str, text: str) -> list[str]:
    """Разбирает список, игнорируя пустые строки и проверяя маркеры элементов."""
    value = trim_trailing_blank_lines(text)
    items: list[str] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        if not line.startswith("- "):
            raise ValueError(f"Строка списка тега {name!r} должна начинаться с '- '")
        item = line[2:].strip()
        if not item:
            raise ValueError(f"Значения списка тега {name!r} не должны быть пустыми")
        items.append(item)
    if not items:
        raise ValueError(f"Значение тега {name!r} не должно быть пустым")
    return items


def parse_star_rating(name: str, text: str) -> int:
    """Разбирает целочисленный рейтинг тега из Markdown."""
    value = trim_trailing_blank_lines(text).strip()
    if not re.fullmatch(r"\d+", value):
        raise ValueError(f"Значение рейтинга {name!r} должно быть целым числом от 1 до 10")
    return int(value)


def parse_bool_value(name: str, text: str) -> bool:
    """Разбирает логическое значение тега из Markdown."""
    value = trim_trailing_blank_lines(text).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"Значение тега {name!r} должно быть true или false")
    return value == "true"
