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
        for path in MusicDir(path=folder).all_music_files:
            relative = path.relative_to(index_dir).as_posix()
            track_id = sha256(relative.encode()).hexdigest()
            tracks[track_id] = Track(
                id=track_id,
                name=path.name,
                directory=folder.relative_to(index_dir).as_posix(),
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
