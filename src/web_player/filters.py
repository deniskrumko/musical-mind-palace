"""Подготовка вариантов и фильтрация треков плейлиста."""

from index import get_albums
from index.tags import get_tag_definitions
from web_player.resources import PlayerQueue, PlaylistFilter, PlaylistPage, Track


def filter_options(queue: PlayerQueue) -> list[dict[str, object]]:
    """Собирает варианты разрешённых тегов из конфигурации и библиотеки."""
    result: list[dict[str, object]] = []
    for key, definition in get_tag_definitions().items():
        if not definition.use_in_filters:
            continue
        values: dict[str, str] = {}
        if definition.choices:
            values.update({value: value for value in definition.choices})
        elif definition.type == "album_selector":
            values.update({key: album.display_name for key, album in get_albums().items()})
        elif definition.type == "bool":
            values = {"true": "Да", "false": "Нет"}
        elif definition.type == "star_rating":
            values = {str(value): str(value) for value in range(1, 11)}
        else:
            for track in queue.tracks.values():
                for tag in track.tags:
                    if tag.name == definition.name:
                        items = tag.value if isinstance(tag.value, list) else [tag.value]
                        values.update({str(value): str(value) for value in items})
        result.append(
            {"key": key, "name": definition.display_name, "type": definition.type, "values": values}
        )
    return result


def matching_tracks(queue: PlayerQueue, criteria: PlaylistFilter) -> list[Track]:
    """Находит все треки директорий, соответствующих условиям поиска."""
    definitions = get_tag_definitions()
    searchable = {
        definition.name for definition in definitions.values() if definition.use_in_text_search
    }
    query = criteria.query.strip().casefold()
    groups: dict[str, list[Track]] = {}
    for track in queue.tracks.values():
        groups.setdefault(track.directory, []).append(track)
    tracks = []
    for directory, items in groups.items():
        texts = [directory.rsplit("/", 1)[-1], *(track.name for track in items)]
        tags = {tag.name: tag.value for tag in items[0].tags}
        if query:
            for tag in items[0].tags:
                if tag.name not in searchable:
                    continue
                values = tag.value if isinstance(tag.value, list) else [tag.value]
                texts.extend(str(value) for value in values)
                texts.extend(tag.display_value or [])
                if isinstance(tag.value, bool):
                    texts.append("Да" if tag.value else "Нет")
        if not any(query in text.casefold() for text in texts):
            continue
        matches = True
        for tag_key, selected in criteria.tags.items():
            if not selected:
                continue
            definition = definitions.get(tag_key)
            if definition is None or not definition.use_in_filters:
                continue
            value = tags.get(definition.name)
            values = value if isinstance(value, list) else [value]
            encoded = [
                str(item).lower() if isinstance(item, bool) else str(item) for item in values
            ]
            if not any(
                option is None and value is None or option in encoded for option in selected
            ):
                matches = False
                break
        if matches:
            tracks.extend(items)
    return tracks


def filtered_page(queue: PlayerQueue, criteria: PlaylistFilter) -> PlaylistPage:
    """Возвращает страницу подходящих треков без изменения очереди."""
    tracks = matching_tracks(queue, criteria)
    return PlaylistPage(
        tracks=tracks[criteria.offset : criteria.offset + 100],
        offset=criteria.offset,
        total=len(tracks),
        revision=queue.playlist_revision,
    )
