"""Определение адреса активного сетевого интерфейса macOS."""

import re
import subprocess


def local_ip() -> str:
    """Получает IPv4 активного интерфейса через route и ifconfig."""
    route = subprocess.run(
        ["/sbin/route", "-n", "get", "default"],
        check=True,
        capture_output=True,
        text=True,
    )
    interface = re.search(r"^\s*interface:\s*(\S+)", route.stdout, re.MULTILINE)
    if interface is None:
        raise ValueError("Не найден активный сетевой интерфейс; укажите --host")
    config = subprocess.run(
        ["/sbin/ifconfig", interface.group(1)],
        check=True,
        capture_output=True,
        text=True,
    )
    address = re.search(r"^\s*inet\s+(\d+\.\d+\.\d+\.\d+)\b", config.stdout, re.MULTILINE)
    if address is None:
        raise ValueError("У активного интерфейса нет IPv4; укажите --host")
    return address.group(1)
