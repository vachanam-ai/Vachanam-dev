"""Submit one required WhatsApp template for one clinic, idempotently."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.schema import Branch  # noqa: E402
from backend.services import wa_template_admin, wa_template_registry  # noqa: E402


async def ensure(clinic: str, template_name: str) -> int:
    spec = next(
        (
            item
            for item in wa_template_admin.SYSTEM_TEMPLATE_DEFINITIONS
            if item["name"] == template_name
        ),
        None,
    )
    if spec is None:
        print("Unknown required template")
        return 1
    async with AsyncSessionLocal() as db:
        branches = (
            await db.execute(select(Branch).where(Branch.name.ilike(f"%{clinic}%")))
        ).scalars().all()
    if len(branches) != 1:
        print(f"Expected one branch, found {len(branches)}")
        return 1
    branch = branches[0]
    current = await wa_template_admin.list_templates(branch)
    if any(item.get("name") == template_name for item in current):
        print(f"exists {template_name}")
        return 0
    await wa_template_admin.create_template(
        branch,
        name=spec["name"],
        category="UTILITY",
        body=spec["body"],
        examples=spec["examples"],
        buttons=spec["buttons"],
        language="en",
    )
    await wa_template_registry.invalidate(branch.id)
    print(f"submitted {template_name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("clinic")
    parser.add_argument("template")
    args = parser.parse_args()
    return asyncio.run(ensure(args.clinic, args.template))


if __name__ == "__main__":
    raise SystemExit(main())
