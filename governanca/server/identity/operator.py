"""Standalone provisioning: python -m governanca.server.identity.operator --help.

Temporary passwords are delivered only to a new file outside the repository.
The operator must hand the file to its intended recipient and delete it.
"""
import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from . import auth


def _restrict_file(file: Path):
    if sys.platform == "win32":
        user = subprocess.run(["whoami"], check=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(["icacls", str(file), "/inheritance:r", "/grant:r", f"{user}:(F)"],
                       check=True, capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Provision Governança identities in GOVERNANCA_DATABASE_URL")
    commands = parser.add_subparsers(dest="command", required=True)
    org = commands.add_parser("organization")
    org.add_argument("code")
    org.add_argument("name")
    dept = commands.add_parser("department")
    dept.add_argument("organization")
    dept.add_argument("code")
    dept.add_argument("name")
    employee = commands.add_parser("employee")
    employee.add_argument("organization")
    employee.add_argument("code")
    employee.add_argument("role", choices=("collaborator", "auditor", "governance"))
    employee.add_argument("--department")
    reset = commands.add_parser("reset")
    reset.add_argument("code")
    for command in (employee, reset):
        command.add_argument("--password-file", type=Path, required=True,
                             help="new, private file OUTSIDE the repository; never printed")
    args = parser.parse_args(argv)
    file = getattr(args, "password_file", None)
    fd = None
    if file is not None:
        repository = Path(__file__).resolve().parents[3]
        if file.resolve().is_relative_to(repository):
            parser.error("password file must be outside the repository")
        # Reserve the destination before changing credentials; never overwrite an existing secret.
        try:
            fd = os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            _restrict_file(file)
        except (OSError, subprocess.CalledProcessError) as exc:
            if fd is not None:
                os.close(fd)
                file.unlink(missing_ok=True)
            parser.error(f"cannot secure exclusive password file: {exc}")
    async def perform():
        if args.command == "organization":
            await auth.provision_organization(args.code, args.name)
        elif args.command == "department":
            await auth.provision_department(args.organization, args.code, args.name)
        elif args.command == "employee":
            return await auth.provision_employee(args.organization, args.code, args.role, args.department)
        else:
            return await auth.reset_password(args.code)
    try:
        password = asyncio.run(perform(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)
        if fd is not None:
            output = os.fdopen(fd, "w", encoding="utf-8")
            fd = None
            with output:
                output.write(password + "\n")
                output.flush()
                os.fsync(output.fileno())
    except BaseException:
        if file is not None:
            if fd is not None:
                os.close(fd)
            file.unlink(missing_ok=True)
        raise
    print("Provisioned. Deliver and remove the private password file." if file else "Provisioned.")


if __name__ == "__main__":
    main()
