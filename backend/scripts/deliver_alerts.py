"""Deliver queued governance alerts through SMTP."""

import argparse
import asyncio

from backend.governance import deliver_due


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="Poll every five seconds")
    args = parser.parse_args()
    while True:
        count = await deliver_due()
        print(f"processed {count} alerts")
        if not args.loop:
            return
        if count == 0:
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
