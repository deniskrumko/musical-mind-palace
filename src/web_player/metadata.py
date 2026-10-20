"""Чтение и сохранение общего индекса музыкальной директории из плеера."""

from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from index import INDEX_FILENAME, Index, get_albums
from index.tags import get_tag_definitions
from web_player.renaming import (
    MetadataConflictError,
    audio_revision,
    check_audio_revision,
    rename_target,
    renamed_audio,
)
from web_player.resources import MetadataEditor, MetadataUpdate, PlayerQueue, Track


def metadata_path(root: Path, track: Track) -> Path:
    """Находит индекс музыкальной директории, исключая выход за границы библиотеки."""
    directory = root / track.directory
    if not directory.resolve().is_relative_to(root) or not directory.is_dir():
        raise ValueError("Музыкальная директория недоступна")
    path = directory / INDEX_FILENAME
    if path.is_symlink():
        raise ValueError("Индекс не должен быть символической ссылкой")
    return path


def read_source(path: Path) -> bytes | None:
    """Читает исходные байты индекса, различая пустой и отсутствующий файл."""
    if path.is_symlink():
        raise ValueError("Индекс не должен быть символической ссылкой")
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def source_revision(source: bytes | None) -> str:
    """Вычисляет версию индекса без нормализации текста и переводов строк."""
    return sha256(source).hexdigest() if source is not None else "missing"


def editor_data(root: Path, track: Track, index: Index, source: bytes | None) -> MetadataEditor:
    """Собирает описание, значения тегов и определения полей формы."""
    return MetadataEditor(
        directory=track.directory,
        track_id=track.id,
        filename=track.path.stem,
        extension=track.path.suffix,
        file_revision=audio_revision(root, track.path),
        description=index.description,
        tags={key: tag.value for key, tag in index.tags.items()},
        revision=source_revision(source),
        definitions=dict(get_tag_definitions()),
        albums=dict(get_albums()),
    )


def load_metadata(root: Path, track: Track) -> MetadataEditor:
    """Загружает актуальные сведения непосредственно из индекса на диске."""
    source = read_source(metadata_path(root, track))
    index = Index.parse(source.decode("utf-8")) if source is not None else Index()
    return editor_data(root, track, index, source)


def check_revision(path: Path, revision: str) -> None:
    """Отклоняет сохранение поверх изменённого на диске индекса."""
    if source_revision(read_source(path)) != revision:
        raise MetadataConflictError("INDEX.md изменился на диске. Изменения не сохранены.")


def save_metadata(
    root: Path, queue: PlayerQueue, track: Track, update: MetadataUpdate
) -> MetadataEditor:
    """Сохраняет имя и индекс с откатом переименования при ошибке записи."""
    path = metadata_path(root, track)
    check_revision(path, update.revision)
    check_audio_revision(root, track.path, update.file_revision)
    target = rename_target(track.path, update.filename)
    index = Index(description=update.description)
    for key, value in update.tags.items():
        index.set(key, value)
    source = index.render()
    parsed = Index.parse(source)
    if parsed.tags != index.tags or parsed.description.rstrip("\n") != index.description.rstrip(
        "\n"
    ):
        raise ValueError("Заголовки ## зарезервированы для тегов. Используйте ### внутри текста.")

    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=path.parent, prefix=".INDEX-", suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(source.encode("utf-8"))
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        check_revision(path, update.revision)
        check_audio_revision(root, track.path, update.file_revision)
        with renamed_audio(track.path, target):
            check_revision(path, update.revision)
            temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    track.path = target
    track.name = target.name
    for item in queue.tracks.values():
        if item.directory == track.directory:
            item.description = parsed.description.strip()
            item.tags = list(parsed.tags.values())
    return editor_data(root, track, parsed, source.encode("utf-8"))
