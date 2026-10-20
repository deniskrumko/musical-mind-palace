"""Читает, проверяет и обновляет Markdown-индексы музыкальных папок."""

import re
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, model_validator

from .resources import LIST_TYPES
from .tags import Tag, get_tag_definitions
from .utils import (
    parse_bool_value,
    parse_list_value,
    parse_star_rating,
    trim_trailing_blank_lines,
)


class Index(BaseModel):
    """Хранит свободное описание и теги, проверенные единым конфигом."""

    description: str = ""
    tags: dict[str, Tag] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_tag_keys(self) -> Self:
        """Проверяет соответствие внутренних ключей тегов конфигурации."""
        definitions = get_tag_definitions() if self.tags else {}
        for key, tag in self.tags.items():
            definition = definitions.get(key)
            if definition is None or definition.name != tag.name or definition.type != tag.type:
                raise ValueError(f"Ключ тега не соответствует конфигурации: {key!r}")
        return self

    @classmethod
    def parse(cls, text: str) -> Self:
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
    def load(cls, path: Path) -> Self:
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

    def merge(self, incoming: Self) -> None:
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
