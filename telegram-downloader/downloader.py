#!/usr/bin/env python3
"""
Telegram Auto File Downloader
Tự động tìm kiếm và tải file (.rar, .zip, .mp4, ...) từ Bot/Channel Telegram
dựa trên danh sách khóa học thu thập từ Extension.
"""

import os
import sys
import json
import re
import asyncio
import argparse
from pathlib import Path
from typing import List, Optional

try:
    from telethon import TelegramClient, events
    from telethon.tl.types import MessageMediaDocument, DocumentAttributeFilename
    from rich.console import Console
    from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
except ImportError:
    print("Vui lòng cài đặt dependency: pip install telethon rich tqdm")
    sys.exit(1)

console = Console()

DEFAULT_CONFIG = {
    "target_chat": "@coursebusters_bot",
    "download_dir": "./downloads",
    "allowed_extensions": [".rar", ".zip", ".7z", ".mp4", ".mkv", ".pdf", ".001", ".002", ".z01", ".z02"],
    "max_concurrent_downloads": 2,
    "skip_existing": True
}


def sanitize_folder_name(name: str) -> str:
    """Tạo tên thư mục an toàn từ tên khóa học."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return clean[:120] if clean else "Unassigned_Course"


def load_config(config_path: Path) -> dict:
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_CONFIG, **data}
        except Exception as e:
            console.print(f"[yellow]Lỗi đọc config.json ({e}), sử dụng cấu hình mặc định.[/yellow]")
    return DEFAULT_CONFIG


def get_credentials():
    api_id = os.environ.get("TELERECON_API_ID")
    api_hash = os.environ.get("TELERECON_API_HASH")
    phone = os.environ.get("TELERECON_PHONE")

    if not api_id or not api_hash:
        console.print("[bold red]Thiếu Telegram API credentials![/bold red]")
        console.print("Hãy chạy script PowerShell [bold cyan].\\start-auto-downloader.ps1[/bold cyan] hoặc thiết lập biến môi trường TELERECON_API_ID và TELERECON_API_HASH.")
        sys.exit(1)

    return int(api_id), api_hash, phone


def parse_input_txt(txt_path: Path) -> List[str]:
    if not txt_path.exists():
        console.print(f"[red]Không tìm thấy file danh sách: {txt_path}[/red]")
        return []

    titles = []
    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            # Nếu dòng có định dạng "Tên khóa\tURL", tách lấy tên khóa
            parts = clean.split("\t")
            title = parts[0].strip()
            if title and not title.startswith("http"):
                titles.append(title)
            elif len(parts) > 1 and parts[1].strip():
                titles.append(parts[1].strip())

    return list(dict.fromkeys(titles))  # Deduplicate keeping order


async def download_file_with_progress(client: TelegramClient, message, save_path: Path, filename: str, progress: Progress):
    task_id = progress.add_task(f"[cyan]{filename[:30]}[/cyan]", total=message.file.size)

    def callback(current, total):
        progress.update(task_id, completed=current)

    try:
        await client.download_media(message, file=str(save_path), progress_callback=callback)
        progress.update(task_id, description=f"[bold green]✔ {filename[:30]}[/bold green]")
    except Exception as e:
        progress.update(task_id, description=f"[bold red]✘ Lỗi: {e}[/bold red]")
        raise e


async def process_course(client: TelegramClient, entity, course_title: str, config: dict):
    console.print(f"\n[bold yellow]🔍 Đang rà quét khóa học:[/bold yellow] [bold white]{course_title}[/bold white]")

    # Nơi lưu file khóa học
    target_dir = Path(config["download_dir"]) / sanitize_folder_name(course_title)
    target_dir.mkdir(parents=True, exist_ok=True)

    allowed_exts = tuple(ext.lower() for ext in config["allowed_extensions"])

    matching_messages = []
    async for message in client.iter_messages(entity, limit=300):
        if not message.media or not isinstance(message.media, MessageMediaDocument):
            continue

        filename = ""
        if message.file and message.file.name:
            filename = message.file.name
        else:
            for attr in getattr(message.media.document, "attributes", []):
                if isinstance(attr, DocumentAttributeFilename):
                    filename = attr.file_name
                    break

        if not filename:
            continue

        # Kiểm tra đuôi file
        if not filename.lower().endswith(allowed_exts):
            continue

        # Kiểm tra tin nhắn có chứa tên khóa học hoặc thuộc cụm file khóa học không
        text = (message.text or "").lower()
        title_lower = course_title.lower()

        # Match bằng từ khóa trong tin nhắn hoặc file
        if title_lower in text or any(word in text for word in title_lower.split() if len(word) > 4):
            matching_messages.append((filename, message))

    if not matching_messages:
        console.print(f"[dim]Chưa tìm thấy file đính kèm cho khóa: {course_title}[/dim]")
        return 0

    console.print(f"[green]Tìm thấy {len(matching_messages)} file hợp lệ cho khóa học![/green]")

    downloaded_count = 0
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        for filename, msg in matching_messages:
            save_file_path = target_dir / filename
            if config["skip_existing"] and save_file_path.exists() and save_file_path.stat().st_size == msg.file.size:
                console.print(f"[dim]⏭ Bỏ qua file đã tải: {filename}[/dim]")
                continue

            try:
                await download_file_with_progress(client, msg, save_file_path, filename, progress)
                downloaded_count += 1
            except Exception as err:
                console.print(f"[red]Thất bại khi tải {filename}: {err}[/red]")

    return downloaded_count


async def main():
    parser = argparse.ArgumentParser(description="Telegram Auto File Downloader")
    parser.add_argument("-i", "--input", help="Đường dẫn file TXT danh sách khóa học (xuất từ Extension)", default=None)
    parser.add_argument("-c", "--chat", help="Target Chat Username/Bot (VD: @coursebusters_bot)", default=None)
    parser.add_argument("-o", "--output", help="Thư mục lưu file tải về", default=None)
    parser.add_argument("--config", help="Đường dẫn file config.json", default="config.json")
    args = parser.parse_args()

    project_root = Path(__file__).parent
    config = load_config(project_root / args.config)

    if args.chat:
        config["target_chat"] = args.chat
    if args.output:
        config["download_dir"] = args.output

    api_id, api_hash, phone = get_credentials()

    session_path = str(project_root / "telegram_downloader.session")
    client = TelegramClient(session_path, api_id, api_hash)

    console.print("[bold cyan]🚀 Đang kết nối tới Telegram Client...[/bold cyan]")
    await client.start(phone=phone)

    me = await client.get_me()
    console.print(f"[bold green]✔ Đã đăng nhập tài khoản Telegram:[/bold green] {me.first_name} (@{me.username or me.id})")

    # Xác định Chat target
    target_chat = config["target_chat"]
    console.print(f"[cyan]Đang kết nối tới Chat/Bot:[/cyan] {target_chat}")
    entity = await client.get_entity(target_chat)

    # Đọc danh sách khóa học
    input_file = args.input
    if not input_file:
        # Tìm file .txt mới nhất trong thư mục gốc hoặc thư mục hiện tại
        txt_files = list(project_root.parent.glob("telegram-*.txt")) + list(project_root.glob("*.txt"))
        if txt_files:
            txt_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            input_file = str(txt_files[0])
            console.print(f"[yellow]Tự động chọn file danh sách mới nhất:[/yellow] {input_file}")
        else:
            console.print("[bold red]Vui lòng cung cấp file danh sách (-i filename.txt)[/bold red]")
            sys.exit(1)

    course_titles = parse_input_txt(Path(input_file))
    console.print(f"[bold green]Đã nạp {len(course_titles)} khóa học từ danh sách.[/bold green]")

    total_downloaded = 0
    for idx, title in enumerate(course_titles, 1):
        console.print(f"\n[bold blue]──────── Progress [{idx}/{len(course_titles)}] ────────[/bold blue]")
        count = await process_course(client, entity, title, config)
        total_downloaded += count

    console.print(f"\n[bold green]🎉 XỬ LÝ HOÀN TẤT! Tổng cộng đã tải {total_downloaded} file vào {config['download_dir']}[/bold green]")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
