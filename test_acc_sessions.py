import asyncio
from telethon import TelegramClient

API_ID = 26522513
API_HASH = "b9fcabdfdbac794eb84e4e93fbfa2fb6"

async def test_session(session_name):
    print(f"--- Testing {session_name} with Telethon ---")
    try:
        client = TelegramClient(f"telegram_media_downloader/{session_name}", API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            print(f"❌ ERROR: {session_name} -> NOT AUTHORIZED")
        else:
            me = await client.get_me()
            print(f"✔ SUCCESS: {session_name} -> User: {me.first_name} (ID: {me.id})")
        await client.disconnect()
    except Exception as e:
        print(f"❌ ERROR: {session_name} -> {type(e).__name__}: {e}")

async def main():
    await test_session("pyrogram")
    await test_session("pyrogram_acc2")
    await test_session("pyrogram_acc3")

if __name__ == "__main__":
    asyncio.run(main())

