"""Проверки представления музыкальных директорий."""

from pathlib import Path

import pytest

from music_dir import MusicDir


def test_from_path_adds_index_file_path_to_tag_errors(tmp_path: Path) -> None:
    """Добавляет путь INDEX.md к ошибке разбора тега."""
    index_path = tmp_path / "Песня" / "INDEX.md"
    index_path.parent.mkdir()
    index_path.write_text("## Unknown tag\nЗначение\n", encoding="utf-8")

    with pytest.raises(ValueError, match=str(index_path)):
        MusicDir.from_path(path=index_path.parent)
