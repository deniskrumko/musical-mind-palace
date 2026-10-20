"""Проверка исходного аудиофайла и переименование без перезаписи занятых имён."""

from collections.abc import Generator
from contextlib import contextmanager
from hashlib import sha256
from os import link
from pathlib import Path
from tempfile import TemporaryDirectory

from core.logicx import is_file


class MetadataConflictError(ValueError):
    """Сообщает об изменении файлов после открытия редактора или занятом имени."""


class RenameRecoveryError(OSError):
    """Сообщает о сохранённой резервной копии при невозможности восстановить исходное имя."""


def audio_revision(root: Path, path: Path) -> str:
    """Определяет версию аудиофайла по имени, идентичности, размеру и времени записи."""
    if not is_file(path) or not path.resolve().is_relative_to(root):
        raise MetadataConflictError(
            "Аудиофайл удалён, переименован или недоступен. Изменения не сохранены."
        )
    info = path.stat()
    identity = (path.name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    return sha256(repr(identity).encode()).hexdigest()


def check_audio_revision(root: Path, path: Path, revision: str) -> None:
    """Отклоняет сохранение после внешнего изменения или замены аудиофайла."""
    if audio_revision(root, path) != revision:
        raise MetadataConflictError("Аудиофайл изменился на диске. Изменения не сохранены.")


def is_case_alias(source: Path, target: Path) -> bool:
    """Распознаёт другое написание того же имени на файловой системе без учёта регистра."""
    return (
        target.exists()
        and not target.is_symlink()
        and source.samefile(target)
        and not any(item.name == target.name for item in source.parent.iterdir())
    )


def rename_target(source: Path, filename: str) -> Path:
    """Проверяет новое имя без расширения и отклоняет занятый путь назначения."""
    if not filename.strip() or filename in {".", ".."}:
        raise ValueError("Укажите непустое имя файла")
    if any(char in filename for char in "/\\") or any(
        ord(char) < 32 or ord(char) == 127 for char in filename
    ):
        raise ValueError("Имя файла не должно содержать разделители пути и управляющие символы")
    target = source.with_name(filename + source.suffix)
    if (
        target != source
        and (target.exists() or target.is_symlink())
        and not is_case_alias(source, target)
    ):
        raise MetadataConflictError("Файл с таким именем уже существует. Выберите другое имя.")
    return target


def link_audio(source: Path, target: Path) -> None:
    """Создаёт новое имя файла, атомарно отклоняя уже занятый путь."""
    try:
        link(source, target, follow_symlinks=False)
    except FileExistsError as error:
        raise MetadataConflictError(
            "Файл с таким именем уже существует. Выберите другое имя."
        ) from error


def remove_audio_link(path: Path, backup: Path) -> None:
    """Удаляет только ссылку на исходный файл, не затрагивая внешнюю подмену пути."""
    if path.is_symlink() or not path.samefile(backup):
        raise MetadataConflictError("Аудиофайл изменился во время сохранения")
    path.unlink()


@contextmanager
def renamed_audio(source: Path, target: Path) -> Generator[None]:
    """Переименовывает аудио и восстанавливает исходное имя при ошибке сохранения индекса."""
    if source == target:
        yield
        return
    case_alias = is_case_alias(source, target)
    folder = TemporaryDirectory(
        dir=source.parent, prefix=".rename-", delete=False, ignore_cleanup_errors=True
    )
    backup = Path(folder.name) / source.name
    try:
        link_audio(source, backup)
        if case_alias:
            remove_audio_link(source, backup)
            try:
                link_audio(backup, target)
            except Exception:
                link_audio(backup, source)
                raise
        else:
            link_audio(backup, target)
            try:
                remove_audio_link(source, backup)
            except Exception:
                remove_audio_link(target, backup)
                raise
        try:
            yield
        except Exception:
            if case_alias:
                remove_audio_link(target, backup)
                link_audio(backup, source)
            else:
                link_audio(backup, source)
                remove_audio_link(target, backup)
            raise
    except Exception as error:
        if backup.exists() and not (
            source.exists()
            and not source.is_symlink()
            and source.samefile(backup)
            and any(item.name == source.name for item in source.parent.iterdir())
        ):
            raise RenameRecoveryError(
                f"Не удалось восстановить прежнее имя. Аудиофайл сохранён в {backup}"
            ) from error
        folder.cleanup()
        raise
    else:
        folder.cleanup()
