"""Provision and assign shared OAuth credentials without exposing tokens."""

import argparse
import asyncio

from sqlalchemy.exc import IntegrityError

from backend.shared_oauth import (assign_credential, create_shared_credential,
                                  set_connector, unassign_credential)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("owner_id")
    create.add_argument("credential_id")
    create.add_argument("connector_employee_code")
    create.add_argument("--rpm", type=int, default=60)
    create.add_argument("--daily", type=int, default=500)
    for name in ("assign", "unassign", "connector"):
        command = commands.add_parser(name)
        command.add_argument("credential_id")
        command.add_argument("employee_code")
    args = parser.parse_args()
    try:
        if args.command == "create":
            await create_shared_credential(args.owner_id, args.credential_id,
                                           args.connector_employee_code, args.rpm, args.daily)
        elif args.command == "assign":
            await assign_credential(args.credential_id, args.employee_code)
        elif args.command == "unassign":
            await unassign_credential(args.credential_id, args.employee_code)
        else:
            await set_connector(args.credential_id, args.employee_code)
    except (ValueError, IntegrityError) as exc:
        parser.exit(1, f"shared OAuth operation failed: {exc if isinstance(exc, ValueError) else 'database constraint'}\n")


if __name__ == "__main__":
    asyncio.run(main())
