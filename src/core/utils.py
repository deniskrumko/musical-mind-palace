"""Общие сетевые и вспомогательные функции."""

import socket


def local_ip() -> str:
    """Определяет IPv4-адрес интерфейса, выбранного для внешнего маршрута."""
    connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        connection.connect(("8.8.8.8", 80))
        return connection.getsockname()[0]
    except OSError as error:
        raise ValueError("Не удалось определить IPv4; укажите --host") from error
    finally:
        connection.close()
