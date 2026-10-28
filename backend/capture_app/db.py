import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from .settings import Settings

SCHEMA_VERSION = "1.1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


@contextmanager
def connect(settings: Settings) -> Iterator[Any]:
    if settings.app_env.lower() == "lab" and not settings.uses_postgres:
        raise ValueError("Lab requires DATABASE_URL for PostgreSQL")
    if settings.uses_postgres:
        database_url = settings.database_url.get_secret_value().replace("postgresql+psycopg://", "postgresql://", 1)
        raw = psycopg.connect(database_url, connect_timeout=10, row_factory=dict_row)
        raw.execute("CREATE SCHEMA IF NOT EXISTS governance_capture")
        raw.execute("SET search_path TO governance_capture, public")
        connection = _PostgresConnection(raw)
    else:
        path: Path = settings.database_path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10, isolation_level="DEFERRED")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class _PostgresConnection:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def execute(self, query: str, parameters: Any = ()) -> Any:
        # shortcut: application SQL uses ? only as bind markers; use a SQL-aware translator before adding literal question marks.
        return self._connection.execute(query.replace("?", "%s"), parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def begin_write(db: Any, *tables: str) -> None:
    if isinstance(db, _PostgresConnection):
        if not tables or any(not table.replace("_", "").isalnum() for table in tables):
            raise ValueError("PostgreSQL write transactions require known table names")
        table_list = ", ".join(sorted(set(tables)))
        db.execute(f"LOCK TABLE {table_list} IN SHARE ROW EXCLUSIVE MODE")
    else:
        db.execute("BEGIN IMMEDIATE")


def _initialize_postgres(db: Any) -> None:
    db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("governanca-schema",))
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    applied = {row["version"] for row in db.execute("SELECT version FROM schema_migrations").fetchall()}
    if SCHEMA_VERSION in applied:
        required = {
            "machines", "interactions", "responses", "capture_events",
            "stream_captures", "artifact_metadata", "machine_nonces", "privacy_audit",
        }
        existing_tables = {
            row["table_name"] for row in db.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
            ).fetchall()
        }
        if not required.issubset(existing_tables):
            raise RuntimeError("PostgreSQL schema version does not match its tables")
        existing_views = {
            row["table_name"] for row in db.execute(
                "SELECT table_name FROM information_schema.views WHERE table_schema = current_schema()"
            ).fetchall()
        }
        view_columns = {
            row["table_name"]: set() for row in db.execute(
                "SELECT DISTINCT table_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name IN ('employees', 'departments')"
            ).fetchall()
        }
        for row in db.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name IN ('employees', 'departments')"
        ).fetchall():
            view_columns[row["table_name"]].add(row["column_name"])
        if (not {"employees", "departments"}.issubset(existing_views) or
                not {"organization_id"}.issubset(view_columns.get("employees", set())) or
                not {"organization_id"}.issubset(view_columns.get("departments", set()))):
            raise RuntimeError("PostgreSQL shared employee views are missing")
        return
    if "1.0" in applied:
        db.execute("""CREATE OR REPLACE VIEW departments AS
            SELECT code AS department_code, name AS department_name, 1::SMALLINT AS active,
                   created_at AS created_at, created_at AS updated_at, id AS department_id, organization_id
            FROM public.departments""")
        db.execute("""CREATE OR REPLACE VIEW employees AS
            SELECT employee.code AS employee_id, employee.code AS person_name,
                   department.code AS department_code,
                   CASE WHEN employee.disabled THEN 0 ELSE 1 END::SMALLINT AS active,
                   employee.created_at AS created_at, employee.created_at AS updated_at,
                   employee.organization_id
            FROM public.employees AS employee
            JOIN public.departments AS department ON department.id = employee.department_id
            WHERE employee.role = 'collaborator'""")
        db.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                   (SCHEMA_VERSION, iso(utc_now())))
        return
    if applied:
        raise RuntimeError("PostgreSQL schema has unsupported migration versions")
    existing = db.execute(
        "SELECT COUNT(*) AS count FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' AND table_name <> 'schema_migrations'"
    ).fetchone()["count"]
    if existing:
        raise RuntimeError("PostgreSQL schema is not at the supported version; migrate it before starting the API")

    statements = (
        """CREATE TABLE machines (
            installation_id TEXT PRIMARY KEY, public_key_json TEXT NOT NULL, key_fingerprint TEXT NOT NULL,
            person_name TEXT, project_id TEXT, created_at TEXT NOT NULL, assigned_at TEXT,
            requested_employee_id TEXT, requested_at TEXT, employee_id TEXT, department_code TEXT,
            google_sub TEXT, revoked_at TEXT
        )""",
        """CREATE VIEW departments AS
            SELECT code AS department_code, name AS department_name, 1::SMALLINT AS active,
                   created_at AS created_at, created_at AS updated_at, id AS department_id, organization_id
            FROM public.departments""",
        """CREATE VIEW employees AS
            SELECT employee.code AS employee_id, employee.code AS person_name,
                   department.code AS department_code,
                   CASE WHEN employee.disabled THEN 0 ELSE 1 END::SMALLINT AS active,
                   employee.created_at AS created_at, employee.created_at AS updated_at,
                   employee.organization_id
            FROM public.employees AS employee
            JOIN public.departments AS department ON department.id = employee.department_id
            WHERE employee.role = 'collaborator'""",
        """CREATE TABLE interactions (
            interaction_id TEXT PRIMARY KEY, client_event_id TEXT NOT NULL UNIQUE, request_fingerprint TEXT NOT NULL,
            device_installation_id TEXT NOT NULL, platform TEXT NOT NULL, account_label TEXT, project_json TEXT NOT NULL,
            conversation_json TEXT NOT NULL, prompt_json TEXT NOT NULL, attachments_json TEXT NOT NULL,
            adapter_version TEXT NOT NULL, status TEXT NOT NULL, observed_at TEXT NOT NULL, received_at TEXT NOT NULL,
            source_ip TEXT, attributed_person TEXT, project_id TEXT, machine_key_fingerprint TEXT,
            attachments_capture_status TEXT NOT NULL DEFAULT 'unavailable',
            attachments_truncated SMALLINT NOT NULL DEFAULT 0 CHECK (attachments_truncated IN (0, 1)),
            employee_id TEXT, department_code TEXT,
            usage_context TEXT NOT NULL DEFAULT 'unknown', usage_context_source TEXT NOT NULL DEFAULT 'unknown'
        )""",
        """CREATE TABLE responses (
            response_id TEXT PRIMARY KEY, interaction_id TEXT NOT NULL REFERENCES interactions(interaction_id) ON DELETE CASCADE,
            client_event_id TEXT NOT NULL UNIQUE, request_fingerprint TEXT NOT NULL, text TEXT NOT NULL,
            capture_status TEXT NOT NULL, adapter_version TEXT, observed_at TEXT NOT NULL, received_at TEXT NOT NULL,
            generated_materials_json TEXT NOT NULL DEFAULT '{\"capture_status\":\"unavailable\",\"items\":[],\"truncated\":false}'
        )""",
        """CREATE TABLE capture_events (
            event_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            interaction_id TEXT REFERENCES interactions(interaction_id) ON DELETE CASCADE,
            event_type TEXT NOT NULL, result TEXT NOT NULL, error_code TEXT, occurred_at TEXT NOT NULL
        )""",
        """CREATE TABLE stream_captures (
            capture_id TEXT PRIMARY KEY, request_fingerprint TEXT NOT NULL,
            device_installation_id TEXT NOT NULL REFERENCES machines(installation_id), attributed_person TEXT NOT NULL,
            machine_key_fingerprint TEXT NOT NULL, platform TEXT NOT NULL, path TEXT NOT NULL,
            request_id INTEGER NOT NULL, status_code INTEGER NOT NULL, content_type TEXT NOT NULL,
            capture_status TEXT NOT NULL, response_chars INTEGER NOT NULL, bytes INTEGER NOT NULL,
            chunks INTEGER NOT NULL, frames INTEGER NOT NULL, done_markers INTEGER NOT NULL,
            protocol_done INTEGER NOT NULL, reader_done INTEGER NOT NULL, reader_aborted_after_done INTEGER NOT NULL,
            truncated INTEGER NOT NULL, stream_elapsed_ms INTEGER NOT NULL, event_types_json TEXT NOT NULL,
            event_shapes_json TEXT NOT NULL, event_sequence_json TEXT NOT NULL, observed_at TEXT NOT NULL,
            received_at TEXT NOT NULL, employee_id TEXT, department_code TEXT
        )""",
        """CREATE TABLE artifact_metadata (
            artifact_id TEXT PRIMARY KEY, request_fingerprint TEXT NOT NULL,
            device_installation_id TEXT NOT NULL REFERENCES machines(installation_id), attributed_person TEXT NOT NULL,
            machine_key_fingerprint TEXT NOT NULL, platform TEXT NOT NULL, source TEXT NOT NULL, file_name TEXT,
            mime_type TEXT, size_bytes INTEGER, conversation_id TEXT, conversation_context_source TEXT,
            size_source TEXT, observed_at TEXT NOT NULL, received_at TEXT NOT NULL, employee_id TEXT, department_code TEXT
        )""",
        """CREATE TABLE machine_nonces (
            installation_id TEXT NOT NULL REFERENCES machines(installation_id) ON DELETE CASCADE,
            nonce TEXT NOT NULL, expires_at TEXT NOT NULL, PRIMARY KEY (installation_id, nonce)
        )""",
        """CREATE TABLE privacy_audit (
            audit_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            event_type TEXT NOT NULL CHECK (event_type IN ('content_read', 'content_read_denied', 'employee_data_deleted')),
            occurred_at TEXT NOT NULL, actor_id TEXT NOT NULL, action TEXT NOT NULL,
            record_count INTEGER NOT NULL CHECK (record_count >= 0), counts_json TEXT NOT NULL DEFAULT '{}'
        )""",
        "CREATE INDEX ix_interactions_received_at ON interactions(received_at)",
        "CREATE INDEX ix_responses_interaction ON responses(interaction_id, received_at)",
        "CREATE INDEX ix_capture_events_interaction ON capture_events(interaction_id, occurred_at)",
        "CREATE INDEX ix_stream_captures_received_at ON stream_captures(received_at)",
        "CREATE INDEX ix_artifact_metadata_received_at ON artifact_metadata(received_at)",
        "CREATE INDEX ix_interactions_analytics_search ON interactions(department_code, employee_id, received_at DESC)",
        "CREATE INDEX ix_privacy_audit_occurred_at ON privacy_audit(occurred_at)",
    )
    for statement in statements:
        db.execute(statement)
    now = iso(utc_now())
    for version in ("0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", SCHEMA_VERSION):
        db.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?) ON CONFLICT (version) DO NOTHING",
            (version, now),
        )


def migrate_postgres(settings: Settings) -> None:
    if not settings.uses_postgres:
        raise ValueError("DATABASE_URL must point to PostgreSQL")
    with connect(settings) as db:
        _initialize_postgres(db)


def _verify_postgres(db: Any) -> None:
    migrations_table = db.execute("SELECT to_regclass('schema_migrations') AS table_name").fetchone()["table_name"]
    if migrations_table is None:
        raise RuntimeError("PostgreSQL schema is missing; run python -m app.migrate_database first")
    applied = {row["version"] for row in db.execute("SELECT version FROM schema_migrations").fetchall()}
    if SCHEMA_VERSION not in applied:
        raise RuntimeError("PostgreSQL schema is not at the supported version; run python -m app.migrate_database")
    required = {
        "machines", "interactions", "responses", "capture_events",
        "stream_captures", "artifact_metadata", "machine_nonces", "privacy_audit",
    }
    existing = {
        row["table_name"] for row in db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        ).fetchall()
    }
    if not required.issubset(existing):
        raise RuntimeError("PostgreSQL schema version does not match its tables")
    views = {row["table_name"] for row in db.execute(
        "SELECT table_name FROM information_schema.views WHERE table_schema = current_schema()"
    ).fetchall()}
    if not {"employees", "departments"}.issubset(views):
        raise RuntimeError("PostgreSQL shared employee views are missing")


def database_tables(settings: Settings) -> set[str]:
    with connect(settings) as db:
        if settings.uses_postgres:
            return {row["table_name"] for row in db.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
            ).fetchall()}
        return {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def initialize(settings: Settings) -> None:
    with connect(settings) as db:
        if settings.uses_postgres:
            _initialize_postgres(db)
            _verify_postgres(db)
            return
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interactions (
                interaction_id TEXT PRIMARY KEY,
                client_event_id TEXT NOT NULL UNIQUE,
                request_fingerprint TEXT NOT NULL,
                device_installation_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                account_label TEXT,
                project_json TEXT NOT NULL,
                conversation_json TEXT NOT NULL,
                prompt_json TEXT NOT NULL,
                attachments_json TEXT NOT NULL,
                adapter_version TEXT NOT NULL,
                status TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                source_ip TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_interactions_received_at ON interactions(received_at);
            CREATE TABLE IF NOT EXISTS responses (
                response_id TEXT PRIMARY KEY,
                interaction_id TEXT NOT NULL REFERENCES interactions(interaction_id) ON DELETE CASCADE,
                client_event_id TEXT NOT NULL UNIQUE,
                request_fingerprint TEXT NOT NULL,
                text TEXT NOT NULL,
                capture_status TEXT NOT NULL,
                adapter_version TEXT,
                observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_responses_interaction ON responses(interaction_id, received_at);
            CREATE TABLE IF NOT EXISTS capture_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                interaction_id TEXT REFERENCES interactions(interaction_id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                result TEXT NOT NULL,
                error_code TEXT,
                occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_capture_events_interaction ON capture_events(interaction_id, occurred_at);
            CREATE TABLE IF NOT EXISTS stream_captures (
                capture_id TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                device_installation_id TEXT NOT NULL REFERENCES machines(installation_id),
                attributed_person TEXT NOT NULL,
                machine_key_fingerprint TEXT NOT NULL,
                platform TEXT NOT NULL,
                path TEXT NOT NULL,
                request_id INTEGER NOT NULL,
                status_code INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                capture_status TEXT NOT NULL,
                response_chars INTEGER NOT NULL,
                bytes INTEGER NOT NULL,
                chunks INTEGER NOT NULL,
                frames INTEGER NOT NULL,
                done_markers INTEGER NOT NULL,
                protocol_done INTEGER NOT NULL,
                reader_done INTEGER NOT NULL,
                reader_aborted_after_done INTEGER NOT NULL,
                truncated INTEGER NOT NULL,
                stream_elapsed_ms INTEGER NOT NULL,
                event_types_json TEXT NOT NULL,
                event_shapes_json TEXT NOT NULL,
                event_sequence_json TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_stream_captures_received_at ON stream_captures(received_at);
            CREATE TABLE IF NOT EXISTS artifact_metadata (
                artifact_id TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                device_installation_id TEXT NOT NULL REFERENCES machines(installation_id),
                attributed_person TEXT NOT NULL,
                machine_key_fingerprint TEXT NOT NULL,
                platform TEXT NOT NULL,
                source TEXT NOT NULL,
                file_name TEXT,
                mime_type TEXT,
                size_bytes INTEGER,
                conversation_id TEXT,
                conversation_context_source TEXT,
                size_source TEXT,
                observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_artifact_metadata_received_at ON artifact_metadata(received_at);
            CREATE TABLE IF NOT EXISTS machines (
                installation_id TEXT PRIMARY KEY,
                public_key_json TEXT NOT NULL,
                key_fingerprint TEXT NOT NULL,
                person_name TEXT,
                project_id TEXT,
                created_at TEXT NOT NULL,
                assigned_at TEXT
            );
            CREATE TABLE IF NOT EXISTS machine_nonces (
                installation_id TEXT NOT NULL REFERENCES machines(installation_id) ON DELETE CASCADE,
                nonce TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (installation_id, nonce)
            );
            INSERT OR IGNORE INTO schema_migrations(version, applied_at)
            VALUES ('0.1', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
            """
        )
        machine_columns = {row["name"] for row in db.execute("PRAGMA table_info(machines)")}
        for name in ("requested_employee_id", "requested_at"):
            if name not in machine_columns:
                db.execute(f"ALTER TABLE machines ADD COLUMN {name} TEXT")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('0.9', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(interactions)")}
        if "attributed_person" not in columns:
            db.execute("ALTER TABLE interactions ADD COLUMN attributed_person TEXT")
            db.execute("ALTER TABLE interactions ADD COLUMN project_id TEXT")
            db.execute("ALTER TABLE interactions ADD COLUMN machine_key_fingerprint TEXT")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('0.2', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
        if "attachments_capture_status" not in columns:
            db.execute("ALTER TABLE interactions ADD COLUMN attachments_capture_status TEXT NOT NULL DEFAULT 'unavailable'")
            db.execute("ALTER TABLE interactions ADD COLUMN attachments_truncated INTEGER NOT NULL DEFAULT 0")
        response_columns = {row["name"] for row in db.execute("PRAGMA table_info(responses)")}
        if "generated_materials_json" not in response_columns:
            db.execute("ALTER TABLE responses ADD COLUMN generated_materials_json TEXT NOT NULL DEFAULT '{\"capture_status\":\"unavailable\",\"items\":[],\"truncated\":false}'")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('0.3', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('0.4', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
        artifact_columns = {row["name"] for row in db.execute("PRAGMA table_info(artifact_metadata)")}
        for name in ("conversation_id", "conversation_context_source", "size_source"):
            if name not in artifact_columns:
                db.execute(f"ALTER TABLE artifact_metadata ADD COLUMN {name} TEXT")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('0.5', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
        for table in ("machines", "interactions", "stream_captures", "artifact_metadata"):
            columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            for name in ("employee_id", "department_code"):
                if name not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS ix_interactions_analytics_search ON interactions(department_code, employee_id, received_at DESC)")
        interaction_columns = {row["name"] for row in db.execute("PRAGMA table_info(interactions)")}
        for name, declaration in (("usage_context", "TEXT NOT NULL DEFAULT 'unknown'"),
                                  ("usage_context_source", "TEXT NOT NULL DEFAULT 'unknown'")):
            if name not in interaction_columns:
                db.execute(f"ALTER TABLE interactions ADD COLUMN {name} {declaration}")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('0.6', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
        machine_columns = {row["name"] for row in db.execute("PRAGMA table_info(machines)")}
        for name in ("google_sub", "revoked_at"):
            if name not in machine_columns:
                db.execute(f"ALTER TABLE machines ADD COLUMN {name} TEXT")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('0.7', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS departments (
                department_code TEXT PRIMARY KEY,
                department_name TEXT NOT NULL,
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY,
                person_name TEXT NOT NULL,
                department_code TEXT NOT NULL REFERENCES departments(department_code),
                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_employees_department ON employees(department_code, active);
            INSERT OR IGNORE INTO schema_migrations(version, applied_at)
            VALUES ('0.8', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
            CREATE TABLE IF NOT EXISTS privacy_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL CHECK (event_type IN ('content_read', 'content_read_denied', 'employee_data_deleted')),
                occurred_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                record_count INTEGER NOT NULL CHECK (record_count >= 0),
                counts_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_privacy_audit_occurred_at ON privacy_audit(occurred_at);
            INSERT OR IGNORE INTO schema_migrations(version, applied_at)
            VALUES ('1.0', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
            """
        )


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def clean_expired(settings: Settings) -> int:
    with connect(settings) as db:
        return _clean_expired(db, settings)


def _clean_expired(db: Any, settings: Settings) -> int:
    db.execute("DELETE FROM machine_nonces WHERE expires_at <= ?", (iso(utc_now()),))
    if settings.uses_postgres:
        cutoff = "CAST(received_at AS TIMESTAMPTZ) < CURRENT_TIMESTAMP - (? * INTERVAL '1 day')"
        audit_cutoff = "CAST(occurred_at AS TIMESTAMPTZ) < CURRENT_TIMESTAMP - (? * INTERVAL '1 day')"
        retention: Any = settings.retention_days
    else:
        cutoff = "julianday(received_at) < julianday('now', ?)"
        audit_cutoff = "julianday(occurred_at) < julianday('now', ?)"
        retention = f"-{settings.retention_days} days"
    cursor = db.execute(f"DELETE FROM interactions WHERE {cutoff}", (retention,))
    db.execute(f"DELETE FROM stream_captures WHERE {cutoff}", (retention,))
    db.execute(f"DELETE FROM artifact_metadata WHERE {cutoff}", (retention,))
    db.execute(f"DELETE FROM privacy_audit WHERE {audit_cutoff}", (retention,))
    return cursor.rowcount


def record_privacy_audit(db: Any, event_type: str, actor_id: str,
                         action: str, record_count: int, counts: dict[str, int] | None = None) -> None:
    db.execute(
        """INSERT INTO privacy_audit(event_type, occurred_at, actor_id, action, record_count, counts_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_type, iso(utc_now()), actor_id, action, record_count, json_dump(counts or {})),
    )


def delete_employee_data(settings: Settings, employee_id: str, actor_id: str) -> dict[str, int]:
    with connect(settings) as db:
        begin_write(db, "artifact_metadata", "capture_events", "interactions", "machine_nonces",
                    "machines", "privacy_audit", "responses", "stream_captures")
        machines = db.execute(
            "SELECT installation_id FROM machines WHERE employee_id = ? OR requested_employee_id = ?",
            (employee_id, employee_id),
        ).fetchall()
        machine_ids = [row["installation_id"] for row in machines]
        clauses = "employee_id = ?"
        interaction_clauses = "i.employee_id = ?"
        values: list[str] = [employee_id]
        if machine_ids:
            placeholders = ", ".join("?" for _ in machine_ids)
            clauses += f" OR (device_installation_id IN ({placeholders}) AND employee_id IS NULL)"
            values.extend(machine_ids)
            interaction_clauses += f" OR (i.device_installation_id IN ({placeholders}) AND i.employee_id IS NULL)"
        counts: dict[str, int] = {}
        counts["responses"] = db.execute(
            f"SELECT COUNT(*) AS count FROM responses r JOIN interactions i USING (interaction_id) WHERE {interaction_clauses}",
            values,
        ).fetchone()["count"]
        counts["capture_events"] = db.execute(
            f"SELECT COUNT(*) AS count FROM capture_events c JOIN interactions i USING (interaction_id) WHERE {interaction_clauses}",
            values,
        ).fetchone()["count"]
        counts["machine_nonces"] = db.execute(
            f"SELECT COUNT(*) AS count FROM machine_nonces WHERE installation_id IN ({', '.join('?' for _ in machine_ids)})",
            machine_ids,
        ).fetchone()["count"] if machine_ids else 0
        for table in ("interactions", "stream_captures", "artifact_metadata"):
            cursor = db.execute(f"DELETE FROM {table} WHERE {clauses}", values)
            counts[table] = cursor.rowcount
        machine_cursor = db.execute(
            "DELETE FROM machines WHERE employee_id = ? OR requested_employee_id = ?",
            (employee_id, employee_id),
        )
        counts["machines"] = machine_cursor.rowcount
        record_count = sum(counts.values())
        record_privacy_audit(db, "employee_data_deleted", actor_id,
                             "CLI app.delete_employee_data", record_count, counts)
        return counts
