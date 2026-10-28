"""Installation signatures and the operator-controlled person/project binding."""

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes, serialization
from fastapi import Depends, HTTPException, Request

from backend.internal_auth import EmployeeInfo
from .db import begin_write, connect, iso, utc_now
from .security import require_capture_token, require_machine_viewer
from .settings import Settings, get_settings


@dataclass(frozen=True)
class Machine:
    installation_id: str
    person_name: str | None
    fingerprint: str
    employee_id: str | None
    department_code: str | None
    google_sub: str | None


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def public_key_from_jwk(jwk: dict) -> ec.EllipticCurvePublicKey:
    try:
        if set(jwk) != {"kty", "crv", "x", "y"} or jwk["kty"] != "EC" or jwk["crv"] != "P-256":
            raise ValueError()
        x, y = _decode(jwk["x"]), _decode(jwk["y"])
        if len(x) != 32 or len(y) != 32:
            raise ValueError()
        return ec.EllipticCurvePublicNumbers(int.from_bytes(x), int.from_bytes(y), ec.SECP256R1()).public_key()
    except (KeyError, TypeError, ValueError, binascii.Error) as error:
        raise HTTPException(status_code=422, detail="Invalid machine public key") from error


def key_fingerprint(key: ec.EllipticCurvePublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return hashlib.sha256(raw).hexdigest()


def project_id_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "chatgpt.com":
        return None
    parts = parsed.path.split("/")
    candidate = parts[2] if len(parts) > 2 and parts[1] == "g" else ""
    return candidate if candidate.startswith("g-p-") and len(candidate) <= 128 and candidate[4:].isalnum() else None


def enroll_machine(installation_id: UUID, jwk: dict, settings: Settings) -> dict:
    key = public_key_from_jwk(jwk)
    fingerprint = key_fingerprint(key)
    identifier = str(installation_id)
    normalized = {field: jwk[field] for field in ("kty", "crv", "x", "y")}
    with connect(settings) as db:
        begin_write(db, "machines")
        existing = db.execute("SELECT key_fingerprint, revoked_at FROM machines WHERE installation_id = ?",
                              (identifier,)).fetchone()
        if existing and existing["key_fingerprint"] != fingerprint:
            raise HTTPException(status_code=409, detail="Installation already has another key")
        if existing and existing["revoked_at"]:
            raise HTTPException(status_code=403, detail="Installation revoked")
        if not existing:
            db.execute("INSERT INTO machines(installation_id, public_key_json, key_fingerprint, created_at) VALUES (?, ?, ?, ?)",
                       (identifier, json.dumps(normalized, sort_keys=True), fingerprint, iso(utc_now())))
    return {"installation_id": identifier, "key_fingerprint": fingerprint}


async def verify_machine_signature(request: Request, settings: Settings) -> Machine | None:
    try:
        identifier = str(UUID(request.headers.get("x-machine-id", "")))
        timestamp = request.headers["x-machine-timestamp"]
        nonce = request.headers["x-machine-nonce"]
        signature = _decode(request.headers["x-machine-signature"])
        if len(signature) != 64 or len(nonce) > 80 or not nonce or not timestamp.isdigit():
            raise ValueError()
        sent_at = int(timestamp)
        if abs(int(utc_now().timestamp() * 1000) - sent_at) > 5 * 60 * 1000:
            raise ValueError()
    except (KeyError, ValueError, TypeError, binascii.Error) as error:
        raise HTTPException(status_code=401, detail="Machine signature missing or expired") from error
    with connect(settings) as db:
        row = db.execute("SELECT * FROM machines WHERE installation_id = ?", (identifier,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Machine not enrolled")
    if row["revoked_at"]:
        raise HTTPException(status_code=403, detail="Installation revoked")
    key = public_key_from_jwk(json.loads(row["public_key_json"]))
    body_hash = hashlib.sha256(await request.body()).hexdigest()
    signed = f"{request.method}\n{request.url.path}\n{timestamp}\n{nonce}\n{body_hash}".encode("utf-8")
    der = utils.encode_dss_signature(int.from_bytes(signature[:32]), int.from_bytes(signature[32:]))
    try:
        key.verify(der, signed, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid machine signature") from error
    with connect(settings) as db:
        begin_write(db, "machine_nonces")
        db.execute("DELETE FROM machine_nonces WHERE expires_at <= ?", (iso(utc_now()),))
        if db.execute("SELECT 1 FROM machine_nonces WHERE installation_id = ? AND nonce = ?",
                      (identifier, nonce)).fetchone():
            raise HTTPException(status_code=409, detail="Machine request already used")
        db.execute("INSERT INTO machine_nonces(installation_id, nonce, expires_at) VALUES (?, ?, ?)",
                   (identifier, nonce, iso(utc_now() + timedelta(minutes=10))))
    return Machine(identifier, row["person_name"], row["key_fingerprint"],
                   row["employee_id"], row["department_code"], row["google_sub"])


async def require_machine_proof(request: Request, employee: EmployeeInfo = Depends(require_machine_viewer),
                                settings: Settings = Depends(get_settings)) -> Machine | None:
    machine = await verify_machine_signature(request, settings)
    if machine is not None and machine.employee_id and machine.employee_id != employee.code:
        raise HTTPException(status_code=403, detail="Installation belongs to another employee")
    if machine is not None and machine.employee_id and machine.department_code != employee.department_code:
        raise HTTPException(status_code=403, detail="Installation assignment is out of date")
    return machine


async def require_machine_signature(request: Request, employee: EmployeeInfo = Depends(require_capture_token),
                                    settings: Settings = Depends(get_settings)) -> Machine | None:
    machine = await verify_machine_signature(request, settings)
    if machine is not None and machine.employee_id != employee.code:
        raise HTTPException(status_code=403, detail="Installation belongs to another employee")
    if machine is not None and machine.department_code != employee.department_code:
        raise HTTPException(status_code=403, detail="Installation assignment is out of date")
    if machine is not None and not (machine.person_name and machine.employee_id and machine.department_code):
        raise HTTPException(status_code=403, detail="Machine assignment pending")
    return machine
