import asyncio
from pyrogram import Client

async def test_session(session_name):
    print(f"--- Testing {session_name} ---")
    try:
        app = Client(f"telegram_media_downloader/{session_name}")
        await app.start()
        me = await app.get_me()
        print(f"✔ SUCCESS: {session_name} -> User: {me.first_name} (ID: {me.id})")
        await app.stop()
    except Exception as e:
        print(f"❌ ERROR: {session_name} -> {type(e).__name__}: {e}")

async def main():
    await test_session("pyrogram")
    await test_session("pyrogram_acc2")
    await test_session("pyrogram_acc3")

if __name__ == "__main__":
    asyncio.run(main())
