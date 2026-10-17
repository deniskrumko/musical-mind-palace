"""Категории музыкальных ресурсов и поддерживаемые расширения."""

CATEGORY_EXTENSIONS: dict[str, set[str]] = {
    "dict": {
        ".m4a",
        ".mp4",
    },
    "bounce": {
        ".mp3",
        ".wav",
    },
    "logic": {
        ".logicx",
        ".band",
    },
    "tab": {
        ".gp",
        ".gpx",
        ".gp5",
        ".gp4",
        ".gpt",
    },
    "image": {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
        ".heic",
        ".heif",
        ".psd",
    },
}

MUSIC_EXTENSIONS: set[str] = set().union(*CATEGORY_EXTENSIONS.values())
