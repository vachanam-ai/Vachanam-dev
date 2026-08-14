"""Bootstrap the FIRST Vachanam super_admin (the chicken-and-egg case).

POST /admin/owners can only be called by an existing super_admin, so the very
first one has to be seeded directly. After this, add more via the admin console.

The user logs in with Google: we create an email-only User row; on their first
Google sign-in the server binds google_sub to it (see backend/routers/auth.py).

Usage:
    python scripts/create_super_admin.py <email> "<Full Name>"

Runs against whatever DATABASE_URL is set (so point it at prod/Neon to seed prod).
Idempotent: if the email already exists it is PROMOTED to super_admin.
"""
import asyncio
import sys

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models.schema import User


async def main(email: str, name: str) -> None:
    email = email.strip().lower()
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing:
            existing.role = "super_admin"
            existing.is_admin = True
            if not existing.name:
                existing.name = name
            await db.commit()
            print(f"PROMOTED existing user to super_admin: {email}")
            return
        db.add(User(
            email=email, name=name, role="super_admin",
            is_admin=True, branch_ids=[], password_hash=None,
        ))
        await db.commit()
        print(f"CREATED super_admin: {email} (Google sign-in will bind on first login)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('Usage: python scripts/create_super_admin.py <email> "<Full Name>"')
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
