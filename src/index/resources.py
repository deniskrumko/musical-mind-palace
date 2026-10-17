"""Чтение и обновление Markdown-индексов музыкальных папок."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

INDEX_FILENAME = "INDEX.md"


class Index(BaseModel):
    """Хранит свободное описание и уникальные теги индекса."""

    description: str = ""
    tags: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> Index:
        """Разбирает индекс, сохраняя текст перед первым тегом."""
        headers = list(re.finditer(r"^##(?!#)[ \t]*([^\r\n]+)", text, re.MULTILINE))
        if not headers:
            return cls(description=text)
        index = cls(description=text[: headers[0].start()])
        for position, header in enumerate(headers):
            end = headers[position + 1].start() if position + 1 < len(headers) else len(text)
            index.set(header.group(1).strip(), text[header.end() : end].strip("\r\n"))
        return index

    @classmethod
    def load(cls, path: Path) -> Index:
        """Читает индекс или возвращает пустой для отсутствующего файла."""
        if path.is_symlink():
            raise ValueError(f"Индекс не должен быть символической ссылкой: {path}")
        return cls.parse(path.read_text(encoding="utf-8")) if path.exists() else cls()

    def set(self, name: str, value: str) -> None:
        """Записывает тег, заменяя его прежнее значение."""
        if not name.strip() or "\n" in name or "\r" in name or name.startswith("#"):
            raise ValueError(f"Недопустимое имя тега: {name!r}")
        self.tags[name.strip()] = value.strip("\r\n")

    def merge(self, incoming: Index) -> None:
        """Объединяет описания и заменяет теги значениями входящего индекса."""
        if incoming.description:
            if self.description and not self.description.endswith("\n\n"):
                self.description += "\n" if self.description.endswith("\n") else "\n\n"
            self.description += incoming.description
        self.tags.update(incoming.tags)

    def render(self) -> str:
        """Собирает Markdown с единственным заголовком для каждого тега."""
        result = self.description
        for name, value in self.tags.items():
            if result and not result.endswith("\n\n"):
                result += "\n" if result.endswith("\n") else "\n\n"
            result += f"## {name}\n{value}\n"
        return result

    def save(self, path: Path) -> None:
        """Сохраняет индекс в UTF-8 без перехода по символическим ссылкам."""
        if path.is_symlink():
            raise ValueError(f"Индекс не должен быть символической ссылкой: {path}")
        path.write_text(self.render(), encoding="utf-8")
