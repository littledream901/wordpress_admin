"""检查 GmailRegistration 的字段"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise
from app.settings.config import settings
from app.models.gmail_registration import GmailRegistration


async def check():
    await Tortoise.init(config=settings.TORTOISE_ORM)
    r = await GmailRegistration.filter(domain='wayasfair.shop').first()
    if r:
        print(f'alias: {r.alias}')
        print(f'domain: {r.domain}')
        print(f'registration_status: {r.registration_status}')
        print(f'registration_email: {r.registration_email}')
        print(f'recovery_email: {r.recovery_email}')
        print(f'构造的邮箱: {r.alias}@{r.domain}')
    else:
        print('未找到记录')
    await Tortoise.close_connections()


asyncio.run(check())
