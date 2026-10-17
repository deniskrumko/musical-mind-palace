"""Запускает веб-плеер музыкальной библиотеки.

Запуск:
    PYTHONPATH=src uv run src/scripts/run_web_player.py --host 0.0.0.0
"""

import argparse
import subprocess
from pathlib import Path

import uvicorn

from scripts import INDEX_DIR
from web_player.app import create_app
from web_player.network import local_ip


def main() -> None:
    """Разбирает параметры и запускает единственный процесс веб-плеера."""
    parser = argparse.ArgumentParser(description="Веб-плеер музыкальной библиотеки")
    host = parser.add_mutually_exclusive_group()
    host.add_argument("--host", help="Адрес сервера (по умолчанию 0.0.0.0)")
    host.add_argument("--auto-host", action="store_true", help="IPv4 активного интерфейса")
    parser.add_argument("--port", type=int, default=8090, help="Порт сервера")
    parser.add_argument("--index-dir", type=Path, default=INDEX_DIR, help="Папка библиотеки")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Порт должен быть от 1 до 65535")
    if not args.index_dir.expanduser().is_dir():
        parser.error(f"Папка библиотеки не существует: {args.index_dir}")
    try:
        address = local_ip() if args.auto_host else args.host or "0.0.0.0"
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(f"Не удалось определить IP: {error}")
    uvicorn.run(create_app(args.index_dir), host=address, port=args.port, workers=1)


if __name__ == "__main__":
    main()
