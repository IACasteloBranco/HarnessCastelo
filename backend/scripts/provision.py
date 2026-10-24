"""Provision the MVP's internal organization, employees, and temporary passwords."""

import argparse
import asyncio

from sqlalchemy.exc import IntegrityError

from backend.internal_auth import (
    disable_employee, provision_department, provision_employee, provision_organization, reset_password,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    organization = commands.add_parser("organization", help="Create the MVP organization")
    organization.add_argument("code")
    organization.add_argument("name")

    department = commands.add_parser("department", help="Create a department")
    department.add_argument("organization_code")
    department.add_argument("code")
    department.add_argument("name")

    employee = commands.add_parser("employee", help="Create an employee with a temporary password")
    employee.add_argument("organization_code")
    employee.add_argument("employee_code")
    employee.add_argument("--role", choices=["collaborator", "governance"], default="collaborator")
    employee.add_argument("--department")

    reset = commands.add_parser("reset-password", help="Issue a new temporary password and revoke sessions")
    reset.add_argument("employee_code")

    disable = commands.add_parser("disable", help="Disable an employee and revoke sessions")
    disable.add_argument("employee_code")

    args = parser.parse_args()
    try:
        if args.command == "organization":
            await provision_organization(args.code, args.name)
        elif args.command == "department":
            await provision_department(args.organization_code, args.code, args.name)
        elif args.command == "employee":
            password = await provision_employee(
                args.organization_code, args.employee_code, args.role, args.department
            )
            print(f"temporary password for {args.employee_code}: {password}")
        elif args.command == "reset-password":
            password = await reset_password(args.employee_code)
            print(f"temporary password for {args.employee_code}: {password}")
        elif args.command == "disable":
            await disable_employee(args.employee_code)
    except (ValueError, IntegrityError) as exc:
        parser.exit(1, f"provisioning failed: {exc if isinstance(exc, ValueError) else 'code or governance account already exists'}\n")


if __name__ == "__main__":
    asyncio.run(main())
