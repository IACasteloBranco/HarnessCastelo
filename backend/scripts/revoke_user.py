import argparse
import asyncio

from backend.store import revoke_user


async def main() -> None:
    parser = argparse.ArgumentParser(description="Revoke OAuth credentials and proxy keys for a user")
    parser.add_argument("user_id")
    args = parser.parse_args()
    count = await revoke_user(args.user_id)
    if count:
        print(f"revoked {count} credential(s) for {args.user_id}")
    else:
        print(f"no account found for {args.user_id}")


if __name__ == "__main__":
    asyncio.run(main())
