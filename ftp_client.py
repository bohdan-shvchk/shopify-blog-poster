#!/usr/bin/env python3
"""
FTP Client для ретро-консолей (Miyoo Mini тощо)
Підключення: ftp://192.168.1.69:5000/
"""

import ftplib
import os
import sys
from pathlib import Path


DEFAULT_HOST = "192.168.1.69"
DEFAULT_PORT = 5000


def connect(host=DEFAULT_HOST, port=DEFAULT_PORT, user="anonymous", password=""):
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=10)
    ftp.login(user, password)
    print(f"Підключено до {host}:{port}")
    print(ftp.getwelcome())
    return ftp


def list_files(ftp, path="."):
    print(f"\nВміст {path}:")
    print("-" * 50)
    items = []
    ftp.retrlines(f"LIST {path}", lambda x: items.append(x))
    for item in items:
        print(item)
    return items


def upload_file(ftp, local_path, remote_dir="/"):
    local_path = Path(local_path)
    if not local_path.exists():
        print(f"Файл не знайдено: {local_path}")
        return False

    remote_path = f"{remote_dir}/{local_path.name}".replace("//", "/")
    size = local_path.stat().st_size
    uploaded = [0]

    def progress(data):
        uploaded[0] += len(data)
        pct = uploaded[0] / size * 100
        bar = "#" * int(pct // 2)
        print(f"\r[{bar:<50}] {pct:.1f}% ({uploaded[0]}/{size} байт)", end="", flush=True)

    print(f"Завантаження: {local_path.name} -> {remote_path}")
    with open(local_path, "rb") as f:
        ftp.storbinary(f"STOR {remote_path}", f, 8192, progress)
    print(f"\nГотово: {local_path.name}")
    return True


def upload_folder(ftp, local_folder, remote_dir="/"):
    folder = Path(local_folder)
    files = list(folder.rglob("*"))
    roms = [f for f in files if f.is_file()]
    print(f"Знайдено {len(roms)} файлів у {folder}")
    for i, rom in enumerate(roms, 1):
        print(f"\n[{i}/{len(roms)}]", end=" ")
        upload_file(ftp, rom, remote_dir)


def download_file(ftp, remote_path, local_dir="."):
    filename = remote_path.split("/")[-1]
    local_path = Path(local_dir) / filename
    print(f"Скачування: {remote_path} -> {local_path}")
    with open(local_path, "wb") as f:
        ftp.retrbinary(f"RETR {remote_path}", f.write)
    print(f"Готово: {local_path}")


def interactive_menu(ftp):
    while True:
        print("\n" + "=" * 50)
        print("FTP Менеджер")
        print("=" * 50)
        print("1. Показати файли на пристрої")
        print("2. Завантажити файл на пристрій")
        print("3. Завантажити папку з іграми")
        print("4. Скачати файл з пристрою")
        print("5. Змінити папку на пристрої")
        print("0. Вийти")
        print("-" * 50)

        choice = input("Вибір: ").strip()

        if choice == "1":
            path = input("Шлях (Enter = поточна): ").strip() or "."
            list_files(ftp, path)

        elif choice == "2":
            local = input("Шлях до файлу на комп'ютері: ").strip()
            remote = input("Папка на пристрої (напр. /Roms/GBA): ").strip() or "/"
            upload_file(ftp, local, remote)

        elif choice == "3":
            local = input("Шлях до папки з іграми: ").strip()
            remote = input("Папка на пристрої (напр. /Roms): ").strip() or "/Roms"
            upload_folder(ftp, local, remote)

        elif choice == "4":
            remote = input("Шлях до файлу на пристрої: ").strip()
            local = input("Куди зберегти (Enter = поточна папка): ").strip() or "."
            download_file(ftp, remote, local)

        elif choice == "5":
            path = input("Новий шлях: ").strip()
            ftp.cwd(path)
            print(f"Поточна папка: {ftp.pwd()}")

        elif choice == "0":
            print("До побачення!")
            break

        else:
            print("Невірний вибір")


def main():
    host = DEFAULT_HOST
    port = DEFAULT_PORT

    if len(sys.argv) >= 2:
        host = sys.argv[1]
    if len(sys.argv) >= 3:
        port = int(sys.argv[2])

    print(f"Підключення до {host}:{port}...")
    try:
        ftp = connect(host, port)
        interactive_menu(ftp)
        ftp.quit()
    except ConnectionRefusedError:
        print("Помилка: не вдалося підключитися. Перевір:")
        print("  - Пристрій увімкнено та FTP запущено")
        print("  - Ти підключений до тієї ж Wi-Fi мережі")
        print(f"  - IP: {host}, порт: {port}")
    except ftplib.all_errors as e:
        print(f"FTP помилка: {e}")
    except KeyboardInterrupt:
        print("\nПерервано користувачем")


if __name__ == "__main__":
    main()
