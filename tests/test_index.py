"""Проверки формата и обновления музыкальных индексов."""

from pathlib import Path

import pytest
from pydantic import ValidationError

import index.resources as index_resources
from index import Index, Tag


def test_parse_list_tags_and_preserve_description() -> None:
    """Разбирает списки, пропускает пустые строки и сохраняет описание."""
    description = "# Песня\nОписание\n\n"
    index = Index.parse(
        description + "## Other names\n- первое имя\n\n- второе имя\n\n## Original folder\nПуть\n\n"
    )
    assert index.description == description
    assert index.tags["other_names"].value == ["первое имя", "второе имя"]
    assert index.tags["original_folder"].value == "Путь"
    assert Index.parse(index.render()) == index


def test_update_removes_duplicate_tags(tmp_path: Path) -> None:
    """Заменяет повторяющийся тег и сохраняет результат в UTF-8."""
    index = Index.parse("## Original folder\nПервое\n## Original folder\nВторое\n")
    index.set("original_folder", "Новое значение")
    path = tmp_path / "INDEX.md"
    index.save(path)
    assert Index.load(path).tags["original_folder"].value == "Новое значение"
    assert path.read_text(encoding="utf-8").count("## Original folder") == 1


def test_merge_overwrites_tags_and_keeps_descriptions() -> None:
    """Оставляет уникальные теги с приоритетом входящего индекса."""
    index = Index.parse(
        "Описание назначения\n\n## Original folder\nСтарое\n## Other names\n- старое имя\n"
    )
    index.merge(Index.parse("Описание источника\n\n## Original folder\nНовое\n"))
    assert index.tags["original_folder"].value == "Новое"
    assert index.tags["other_names"].value == ["старое имя"]
    assert "Описание назначения" in index.description
    assert "Описание источника" in index.description


def test_tag_validation_uses_configured_names_types_and_values() -> None:
    """Отклоняет теги, имена и значения которых не соответствуют конфигу."""
    assert Tag(name="Original folder", type="string", value="Папка")
    assert Tag(name="Other names", type="list", value=["Имя"])
    with pytest.raises(ValidationError):
        Tag(name="Unknown", type="string", value="Значение")
    with pytest.raises(ValidationError):
        Tag(name="Original folder", type="list", value=["Значение"])
    with pytest.raises(ValidationError):
        Tag(name="Original folder", type="string", value="Первая\nВторая")
    with pytest.raises(ValidationError):
        Tag(name="Other names", type="list", value=[])


def test_star_rating_is_an_integer_between_one_and_ten() -> None:
    """Читает рейтинг как целое число и ограничивает шкалу значениями от 1 до 10."""
    index = Index.parse("## Rating\n10\n")
    assert index.tags["rating"].value == 10
    assert Index.parse(index.render()).tags["rating"].value == 10
    assert Tag(name="Rating", type="star_rating", value=1).value == 1
    for value in (0, 11, "10", 1.5):
        with pytest.raises(ValidationError):
            Tag(name="Rating", type="star_rating", value=value)
    with pytest.raises(ValueError, match="целым числом"):
        Index.parse("## Rating\n10.0\n")


def test_text_and_choice_tags_use_configured_values() -> None:
    """Сохраняет формат текста и проверяет варианты выбора по конфигу."""
    lyrics = Index.parse("## Lyrics\nПервая строка\n\nВторая строка\n\n")
    assert lyrics.tags["lyrics"].value == "Первая строка\n\nВторая строка"
    assert Index.parse(lyrics.render()) == lyrics
    assert Tag(name="Genre", type="single_choice", value="heavy")
    assert Tag(name="Mood", type="multi_choice", value=["sad", "funk"])
    with pytest.raises(ValidationError):
        Tag(name="Genre", type="single_choice", value="unknown")
    with pytest.raises(ValidationError):
        Tag(name="Mood", type="multi_choice", value=["unknown"])


def test_invalid_list_syntax_is_rejected() -> None:
    """Требует маркер '- ' у каждой непустой строки списка."""
    with pytest.raises(ValueError, match="должна начинаться"):
        Index.parse("## Other names\nобычная строка\n")
    with pytest.raises(ValueError, match="не должны быть пустыми"):
        Index.parse("## Other names\n- \n")


def test_trims_only_trailing_blank_lines_from_string_values() -> None:
    """Удаляет завершающие пустые строки, сохраняя внутренние переносы текста."""
    index = Index.parse("## Original folder\nПуть\n\n")
    assert index.tags["original_folder"].value == "Путь"
    assert index_resources.trim_trailing_blank_lines("Первая\n\nВторая\n\n") == "Первая\n\nВторая"


def test_unknown_tag_and_empty_values_are_rejected() -> None:
    """Отклоняет незарегистрированные заголовки и пустые значения."""
    with pytest.raises(ValueError, match="не описан"):
        Index.parse("## Unregistered\nСпокойный\n")
    with pytest.raises(ValidationError):
        Tag(name="Original folder", type="string", value="\n\n")


def test_config_rejects_duplicate_markdown_names() -> None:
    """Не допускает неоднозначные имена заголовков в конфигурации."""
    config = """
[tag.first]
name = "Duplicate"
type = "string"

[tag.second]
name = "Duplicate"
type = "text"
"""
    with pytest.raises(ValueError, match="уникальными"):
        index_resources.parse_tag_config(config)


def test_config_parses_choice_options_and_rejects_missing_choices() -> None:
    """Читает choices у тегов выбора и требует список вариантов."""
    config = """
[tag.genre]
name = "Genre"
type = "single_choice"
choices = ["metal", "folk"]
"""
    definitions = index_resources.parse_tag_config(config)
    assert definitions["genre"].choices == ("metal", "folk")
    assert definitions["genre"].display_name == "Genre"

    definitions_with_display_name = index_resources.parse_tag_config(
        '[tag.genre]\nname = "Genre"\ndisplay_name = "Жанр"\ntype = "single_choice"\n'
        'choices = ["metal"]'
    )
    assert definitions_with_display_name["genre"].display_name == "Жанр"

    with pytest.raises(ValidationError):
        index_resources.parse_tag_config('[tag.genre]\nname = "Genre"\ntype = "multi_choice"')


def test_config_is_read_once_per_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Кэширует разобранный конфиг и не перечитывает файл при создании тегов."""
    config_path = tmp_path / "tags.toml"
    config_path.write_text(
        '[tag.original_folder]\nname = "Original folder"\ntype = "string"\n',
        encoding="utf-8",
    )
    original_read_text = Path.read_text
    reads = 0

    def count_config_reads(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal reads
        if path == config_path:
            reads += 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(index_resources, "TAG_CONFIG_PATH", config_path)
    monkeypatch.setattr(Path, "read_text", count_config_reads)
    index_resources.get_tag_definitions.cache_clear()
    try:
        Tag(name="Original folder", type="string", value="Первая папка")
        Tag(name="Original folder", type="string", value="Вторая папка")
        assert reads == 1
    finally:
        index_resources.get_tag_definitions.cache_clear()


def test_missing_index(tmp_path: Path) -> None:
    """Возвращает пустой индекс для отсутствующего файла."""
    assert Index.load(tmp_path / "INDEX.md") == Index()
