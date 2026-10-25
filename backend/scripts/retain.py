"""Run one daily raw-retention and aggregate cleanup pass."""

import asyncio
import logging

from backend.retention import retain_daily


async def main() -> None:
    count = await retain_daily()
    print(f"deleted {count} expired runs")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        logging.exception("retention failed; transaction rolled back")
        raise
