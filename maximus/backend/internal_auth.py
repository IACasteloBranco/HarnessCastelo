"""Compatibility exports for the shared identity service."""

from shared.identity.auth import (
    EXTENSION_SESSION_DURATION,
    LOCK_DURATION,
    SESSION_DURATION,
    EmployeeInfo,
    change_password,
    disable_employee,
    login,
    logout,
    provision_department,
    provision_employee,
    provision_organization,
    renew_extension_session,
    reset_password,
    resolve_session,
)

__all__ = [
    "EXTENSION_SESSION_DURATION", "LOCK_DURATION", "SESSION_DURATION", "EmployeeInfo",
    "change_password", "disable_employee", "login", "logout", "provision_department",
    "provision_employee", "provision_organization", "renew_extension_session", "reset_password",
    "resolve_session",
]
