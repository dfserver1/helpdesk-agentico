# ============================================================
# HelpDesk Enterprise Copilot - Seed initial super-admin
# Creates the platform super-admin from settings (ADMIN_EMAIL/ADMIN_PASSWORD).
# Idempotent: updates password/role if the admin already exists.
# Usage:  python scripts/seed.py
# ============================================================

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from auth.security import hash_password  # noqa: E402
from config.settings import get_settings  # noqa: E402
from core.exceptions import ValidationError  # noqa: E402
from database.models import User, close_db, init_db, SessionLocal  # noqa: E402


async def main():
    settings = get_settings()

    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        raise ValidationError(
            "ADMIN_EMAIL and ADMIN_PASSWORD must be set in the environment before seeding."
        )

    await init_db()
    try:
        async with SessionLocal() as session:
            email = settings.ADMIN_EMAIL.lower()
            existing = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()

            if existing is not None:
                existing.hashed_password = hash_password(settings.ADMIN_PASSWORD)
                existing.is_superuser = True
                existing.is_active = True
                existing.role = "admin"
                await session.commit()
                print(f"Admin updated: {email}")
                return

            admin = User(
                email=email,
                username="admin",
                full_name="Platform Administrator",
                hashed_password=hash_password(settings.ADMIN_PASSWORD),
                role="admin",
                is_superuser=True,
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            print(f"Admin created: {email}")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())