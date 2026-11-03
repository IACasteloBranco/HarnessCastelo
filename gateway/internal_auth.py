"""Backward-compatible import path for the internal authentication routes."""

from governanca.server.auth_api import (
    COOKIE_NAME,
    COOKIE_PATH,
    EXTENSION_ORIGIN,
    LoginBody,
    PasswordBody,
    SensitiveTextBody,
    EmployeeInfo,
    EXTENSION_SESSION_DURATION,
    SESSION_DURATION,
    _check_origin,
    change_password,
    change_password_route,
    current_employee,
    extension_employee,
    extension_inspect_route,
    extension_login_route,
    extension_logout_route,
    extension_me_route,
    extension_renew_route,
    login_route,
    login,
    logout,
    logout_route,
    me_route,
    renew_extension_session,
    resolve_session,
    router,
)
from governanca.server.data_protection import Action, Category, inspect as inspect_sensitive_text
from governanca.server.sensitive_data_protection import InspectionUnavailable, inspect_sensitive_data

__all__ = [
    "COOKIE_NAME", "COOKIE_PATH", "EXTENSION_ORIGIN", "LoginBody", "PasswordBody",
    "SensitiveTextBody", "EmployeeInfo", "EXTENSION_SESSION_DURATION", "SESSION_DURATION",
    "Action", "Category", "InspectionUnavailable",
    "_check_origin", "change_password", "change_password_route", "current_employee",
    "extension_employee", "extension_inspect_route", "extension_login_route",
    "extension_logout_route", "extension_me_route", "extension_renew_route", "login",
    "inspect_sensitive_data", "inspect_sensitive_text", "login_route", "logout", "logout_route",
    "me_route", "renew_extension_session",
    "resolve_session", "router",
]
