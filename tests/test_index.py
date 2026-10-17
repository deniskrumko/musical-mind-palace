"""Проверки формата и обновления музыкальных индексов."""

from pathlib import Path

from index import Index


def test_multiline_tags_and_description() -> None:
    """Сохраняет описание и отличает заголовки тегов от текста значений."""
    description = "# Песня\nОписание\n\n"
    index = Index.parse(
        description + "## Lyrics\nСтрока\n### Припев\nТекст ## внутри\n\n## Mood\nГрусть\n"
    )
    assert index.description == description
    assert index.tags == {
        "Lyrics": "Строка\n### Припев\nТекст ## внутри",
        "Mood": "Грусть",
    }
    assert Index.parse(index.render()) == index


def test_update_removes_duplicate_tags(tmp_path: Path) -> None:
    """Заменяет повторяющийся тег и сохраняет результат в UTF-8."""
    index = Index.parse("## Mood\nПервое\n## Mood\nВторое\n")
    index.set("Mood", "Новое\nзначение")
    path = tmp_path / "INDEX.md"
    index.save(path)
    assert Index.load(path).tags == {"Mood": "Новое\nзначение"}
    assert path.read_text().count("## Mood") == 1


def test_merge_overwrites_tags_and_keeps_descriptions() -> None:
    """Оставляет уникальные теги с приоритетом входящего индекса."""
    index = Index.parse("Описание назначения\n\n## Mood\nСтарое\n## Keep\nДа\n")
    index.merge(Index.parse("Описание источника\n\n## Mood\nНовое\n"))
    assert index.tags == {"Mood": "Новое", "Keep": "Да"}
    assert "Описание назначения" in index.description
    assert "Описание источника" in index.description


def test_missing_index(tmp_path: Path) -> None:
    """Возвращает пустой индекс для отсутствующего файла."""
    assert Index.load(tmp_path / "INDEX.md") == Index()
