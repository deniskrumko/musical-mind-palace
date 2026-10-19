"""Сбор музыкальных файлов из индексированной библиотеки."""

from hashlib import sha256
from pathlib import Path

from index.utils import get_music_dirs
from music_dir import MusicDir
from web_player.resources import PlayerQueue, Track


def scan_library(index_dir: Path) -> PlayerQueue:
    """Собирает очередь в порядке директорий и их музыкальных файлов."""
    index_dir = index_dir.expanduser().resolve()
    tracks: dict[str, Track] = {}
    directories = get_music_dirs(index_dir)
    for folder in directories:
        music_dir = MusicDir.from_path(path=folder)
        index = music_dir.index
        description = index.description.strip() if index else ""
        tags = list(index.tags.values()) if index else []
        music_files = music_dir.all_music_files
        music_count = len(music_files)
        logic_count = len(music_dir.logic_files)
        tab_count = len(music_dir.tab_files)
        for path in music_files:
            relative = path.relative_to(index_dir).as_posix()
            track_id = sha256(relative.encode()).hexdigest()
            tracks[track_id] = Track(
                id=track_id,
                name=path.name,
                directory=folder.relative_to(index_dir).as_posix(),
                description=description,
                tags=tags,
                music_count=music_count,
                logic_count=logic_count,
                tab_count=tab_count,
                path=path,
            )
    keys = list(tracks)
    return PlayerQueue(
        tracks=tracks,
        order=keys,
        total_directories=len(directories),
        current_id=keys[0] if keys else None,
        remaining=keys[1:],
    )
