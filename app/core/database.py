from prisma import Prisma

db = Prisma()


async def connect_db() -> None:
    """DB 연결"""
    if not db.is_connected():
        await db.connect()


async def disconnect_db() -> None:
    """DB 연결 해제"""
    if db.is_connected():
        await db.disconnect()
