import os
import sys
import time
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).parent
ORIGINAL_PROFILE_DIR = BASE_DIR / "Chrome_Telegram_Profile"
PROFILE_DIR = BASE_DIR / "Chrome_Telegram_Profile_copy"
DOWNLOAD_DIR = BASE_DIR / "browser_downloads_test"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Copy profile sang folder temp (bỏ qua Cache & Lock files)
import shutil
if ORIGINAL_PROFILE_DIR.exists():
    try:
        if PROFILE_DIR.exists():
            shutil.rmtree(str(PROFILE_DIR), ignore_errors=True)
        shutil.copytree(
            str(ORIGINAL_PROFILE_DIR),
            str(PROFILE_DIR),
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("*.lock", "SingletonLock", "LOCK", "GPUCache*", "Cache*", "Code Cache*")
        )
    except Exception as e:
        print(f"[WARN] Copy profile warning: {e}")

# Tìm Chrome binary trên Windows
def get_chrome_executable() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

async def run_test():
    print("==========================================")
    print("🚀 BẮT ĐẦU THỬ NGHIỆM TẢI FILE QUA BROWSER (PLAYWRIGHT)")
    print(f"📁 Chrome Profile: {PROFILE_DIR}")
    print(f"📁 Save Directory: {DOWNLOAD_DIR}")
    chrome_exe = get_chrome_executable()
    print(f"🌐 Chrome Executable: {chrome_exe}")
    print("==========================================")

    async with async_playwright() as p:
        # Khởi chạy Chrome Persistent Context
        launch_kwargs = {
            "user_data_dir": str(PROFILE_DIR),
            "headless": False,
            "args": [
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
            ],
            "viewport": {"width": 1280, "height": 800},
            "accept_downloads": True
        }
        if chrome_exe:
            launch_kwargs["executable_path"] = chrome_exe

        context = await p.chromium.launch_persistent_context(**launch_kwargs)

        page = context.pages[0] if context.pages else await context.new_page()

        print("[INFO] Đang mở trực tiếp chat Bot: https://web.telegram.org/a/#@coursebusters_bot ...")
        await page.goto("https://web.telegram.org/a/#@coursebusters_bot", wait_until="domcontentloaded")
        await asyncio.sleep(8)

        # 1. Đóng thẻ thông báo bảo mật "YES, IT'S ME" nếu xuất hiện
        print("[INFO] Đang kiểm tra và đóng thẻ thông báo bảo mật...")
        try:
            sec_btn = page.locator('text="YES, IT\'S ME"').first
            if await sec_btn.is_visible(timeout=3000):
                await sec_btn.click(force=True)
                print("✔ Đã click 'YES, IT'S ME' đóng thẻ bảo mật!")
                await asyncio.sleep(2)
        except Exception:
            pass

        # 2. Click chọn nhóm Relay 'Getfile2'
        print("[INFO] Đang click chọn nhóm Relay 'Getfile2'...")
        try:
            getfile_btn = page.locator('div:has-text("Getfile2"), span:has-text("Getfile2"), .peer-title:has-text("Getfile2")').first
            await getfile_btn.click(force=True)
            print("✔ Đã click chọn nhóm Getfile2!")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"⚠️ Cảnh báo click Getfile2: {e}")

        # Chụp ảnh giao diện trong nhóm Getfile2
        relay_img = BASE_DIR / "telegram_getfile2_success.png"
        await page.screenshot(path=str(relay_img))
        print(f"[SUCCESS] 📸 Đã chụp ảnh màn hình nhóm Getfile2: {relay_img}")

        # 2. Tìm tất cả các file nén / media document đính kèm
        print("[INFO] Đang tìm các nút Download / File đính kèm trong nhóm Getfile2...")
        selectors = [
            'button.download-button', 'i.icon-download', '.media-document-action',
            '.document-message', 'button[title*="Download"]', '.file-button',
            '.document-utils', '.action-icon', 'button.btn-icon', '.media-doc',
            'div[class*="document"]', 'div[class*="file"]'
        ]
        btn_to_click = None
        for sel in selectors:
            elems = await page.query_selector_all(sel)
            if elems:
                print(f"  - Tìm thấy selector '{sel}': {len(elems)} elements")
                btn_to_click = elems[-1]
                break

        if not btn_to_click:
            # Thử click vào bất kỳ file tài liệu đính kèm nào trên màn hình
            doc_elems = await page.query_selector_all('.message-media, .document-message, div[class*="message"]')
            if doc_elems:
                print(f"[INFO] Tìm thấy {len(doc_elems)} tin nhắn media đính kèm, chọn file mới nhất...")
                btn_to_click = doc_elems[-1]

        if btn_to_click:
            print("🚀 Bắt đầu kích hoạt Tải File qua Browser...")
            start_time = time.time()

            try:
                async with page.expect_download(timeout=180000) as download_info:
                    await btn_to_click.click()
                    print("[INFO] Đã click nút Download, đang chờ trình duyệt tải file...")

                download = await download_info.value
                dest_path = DOWNLOAD_DIR / download.suggested_filename
                await download.save_as(dest_path)

                end_time = time.time()
                elapsed = end_time - start_time
                file_size_bytes = dest_path.stat().st_size
                file_size_mb = file_size_bytes / (1024 * 1024)
                speed_mbs = file_size_mb / elapsed if elapsed > 0 else 0

                print("\n==========================================")
                print("🎉 KẾT QUẢ THỬ NGHIỆM TẢI FILE QUA BROWSER THỰC TẾ:")
                print(f"📦 Tên File: {download.suggested_filename}")
                print(f"💾 Dung lượng: {file_size_mb:.2f} MB ({file_size_bytes:,} bytes)")
                print(f"⏱️ Thời gian tải: {elapsed:.2f} giây")
                print(f"⚡ TỐC ĐỘ TẢI BROWSER THỰC TẾ: {speed_mbs:.2f} MB/s")
                print("==========================================")

            except Exception as e:
                print(f"⚠️ Lỗi khi theo dõi sự kiện Download: {e}")
        else:
            print("⚠️ Không tìm thấy nút Download đính kèm trên giao diện hiện tại.")

        print("[INFO] Tự động đóng trình duyệt sau 10 giây...")
        await asyncio.sleep(10)
        await context.close()

if __name__ == "__main__":
    asyncio.run(run_test())
