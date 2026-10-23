import argparse
import asyncio

from store import issue_client_key


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create and register a proxy client key")
    parser.add_argument("credential_id")
    args = parser.parse_args()
    print(await issue_client_key(args.credential_id))


if __name__ == "__main__":
    asyncio.run(main())
