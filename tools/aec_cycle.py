"""Run an isolated AEC rehearsal or supervised maintenance scan."""

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aec.communication.broker import Broker
from aec.communication.schemas import Message, MessageType, ReviewRequest
from aec.engineering.gates import CommandGate, GateResult, run_gates
from aec.engineering.git import commit_hash, create_worktree
from aec.engineering.loop import AdversarialLoop
from aec.engineering.models import QAReviewResult
from aec.execution.adapters.codex_cli import CodexCliAdapter
from aec.execution.base import ExecutionAdapter
from aec.execution.manager import ExecutionManager
from aec.execution.models import ExecutionRequest, ExecutionResult, ExecutionStatus
from aec.execution.policy import ExecutionPolicy
from aec.security.identities import Role


PROJECT = Path(__file__).resolve().parents[1]
RUNS = PROJECT / ".audit" / "aec"
PROBE = "aec-local-review.txt"
GATE = CommandGate(
    gate_id="existing-tests",
    argv=(
        sys.executable, "-m", "unittest", "-v",
        "gateway.tests.test_proxy", "backend.tests.test_store", "gateway.tests.test_internal_auth",
        "gateway.tests.test_shared_oauth",
    ),
)


def git(directory: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(directory), *args],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def snapshot(target: Path) -> None:
    target.mkdir(parents=True)
    names = set(git(PROJECT, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0"))
    for name in sorted(names - {b""}):
        relative = Path(os.fsdecode(name))
        source = PROJECT / relative
        if not source.exists():
            continue
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"snapshot only accepts regular files: {relative}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    git(target, "init", "-q")
    git(target, "add", "-A")
    git(target, "-c", "user.name=AEC", "-c", "user.email=aec@localhost", "commit", "-qm", "AEC local baseline")


class LocalAgents(ExecutionAdapter):
    async def healthcheck(self) -> bool:
        return True

    async def cancel(self, execution_id: str) -> bool:
        return False

    async def execute(
        self, request: ExecutionRequest, provider_session_id: str | None = None
    ) -> ExecutionResult:
        context = json.loads(request.prompt)
        if request.agent_id == "implementer":
            ready = context["iteration"] > 1
            (request.working_directory / PROBE).write_text(
                "status=ready\n" if ready else "status=needs-review\n",
                encoding="utf-8",
            )
            output = "Updated the local review marker"
        elif request.agent_id == "qa":
            ready = (request.working_directory / PROBE).read_text(encoding="utf-8") == "status=ready\n"
            output = json.dumps({
                "task_id": context["output_contract"]["task_id"],
                "iteration": context["iteration"],
                "reviewed_commit": context["reviewed_commit"],
                "review_status": "PASSED" if ready else "FAILED",
                "findings": [] if ready else [{
                    "finding_id": "review-marker",
                    "severity": "MEDIUM",
                    "category": "correctness",
                    "title": "Review marker is not ready",
                    "description": "The marker must contain status=ready",
                    "file": PROBE,
                    "status": "REPRODUCED",
                    "reproduction_steps": [f"Read {PROBE} in the QA worktree"],
                    "expected_behavior": "status=ready",
                    "actual_behavior": "status=needs-review",
                }],
            })
        else:
            raise ValueError(f"unexpected agent: {request.agent_id}")
        now = datetime.now(timezone.utc)
        return ExecutionResult(
            execution_id=request.execution_id,
            agent_id=request.agent_id,
            status=ExecutionStatus.SUCCEEDED,
            output=output,
            started_at=now,
            finished_at=now,
        )


class CleanCodexAdapter(CodexCliAdapter):
    async def execute(
        self, request: ExecutionRequest, provider_session_id: str | None = None
    ) -> ExecutionResult:
        result = await super().execute(request, provider_session_id)
        if request.agent_id == "implementer":
            for cache in request.working_directory.rglob("__pycache__"):
                if cache.is_dir() and not cache.is_symlink():
                    shutil.rmtree(cache)
        return result


def scan_status(review: QAReviewResult, gates: list[GateResult]) -> str:
    return (
        "NO_CHANGES"
        if review.review_status == "PASSED" and gates
        and all(gate.status == "PASSED" for gate in gates)
        else "NEEDS_REVIEW"
    )


async def start() -> int:
    if not os.environ.get("HARNESS_TEST_DATABASE_URL"):
        raise ValueError("HARNESS_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database")
    run_id = str(uuid4())
    root = RUNS / run_id
    source = root / "source"
    worktrees = root / "worktrees"
    snapshot(source)
    worktrees.mkdir()
    broker = Broker(root / "aec.sqlite")
    orchestrator = broker.register("orchestrator", Role.ORCHESTRATOR)
    implementer = broker.register("implementer", Role.IMPLEMENTER)
    qa = broker.register("qa", Role.QA)
    quality_gate = broker.register("quality-gate", Role.QUALITY_GATE)
    policy = ExecutionPolicy((source, worktrees))
    manager = ExecutionManager(
        broker,
        {"local": LocalAgents()},
        [worktrees],
        policy=policy,
        writable_agents=frozenset({"implementer"}),
    )
    loop = AdversarialLoop(
        broker, manager, orchestrator, implementer, qa, quality_gate,
        source, worktrees,
        (GATE,),
        executor="local",
        max_iterations=2,
        local_approvers=frozenset({"local-supervisor"}),
    )
    loop.create(
        "aec-local-rehearsal",
        "Exercise implementation, independent QA, rework and the existing test gate",
        ("QA finds the first marker", "the second marker passes QA and existing tests"),
        (PROBE,),
        run_id=run_id,
    )
    status = await loop.run(run_id)
    print(json.dumps({"run_id": run_id, "status": status, "database": str(root / "aec.sqlite")}))
    return 0 if status == "WAITING_APPROVAL" else 1


async def scan() -> int:
    if not os.environ.get("HARNESS_TEST_DATABASE_URL"):
        raise ValueError("HARNESS_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database")
    run_id = str(uuid4())
    root = RUNS / run_id
    source = root / "source"
    worktrees = root / "worktrees"
    snapshot(source)
    worktrees.mkdir()
    base = commit_hash(source)
    qa_path = worktrees / f"{run_id}-qa-scan"
    create_worktree(source, qa_path, base)
    broker = Broker(root / "aec.sqlite")
    orchestrator = broker.register("orchestrator", Role.ORCHESTRATOR)
    implementer = broker.register("implementer", Role.IMPLEMENTER)
    qa = broker.register("qa", Role.QA)
    quality_gate = broker.register("quality-gate", Role.QUALITY_GATE)
    with broker.db.connect() as db:
        db.execute(
            "CREATE TABLE maintenance_scan (run_id TEXT PRIMARY KEY, status TEXT NOT NULL, "
            "base_commit TEXT NOT NULL, review TEXT, gate_result TEXT)"
        )
        db.execute("INSERT INTO maintenance_scan VALUES (?,?,?,NULL,NULL)", (run_id, "RUNNING", base))
    policy = ExecutionPolicy((source, worktrees))
    adapter = CleanCodexAdapter(policy=policy)
    if not await adapter.healthcheck():
        raise RuntimeError("Codex CLI 0.163+ and an active login are required")
    manager = ExecutionManager(
        broker, {"codex": adapter}, [worktrees], policy=policy,
        writable_agents=frozenset({"implementer"}),
    )
    prompt = (
        "Review this repository for reproducible logic bugs or measurable inefficiency only. "
        "Do not edit files. Preserve each module's intended contract; exclude new features, "
        "style suggestions and speculative findings. Inspect callers and tests. "
        "Return only JSON matching AEC QAReviewResult: task_id='maintenance-scan', "
        f"iteration=1, reviewed_commit='{base}', review_status=PASSED/FAILED/INCONCLUSIVE, "
        "findings=[{finding_id,severity,category,title,description,file,line,status,"
        "reproduction_steps,expected_behavior,actual_behavior}], tests_executed, limitations. "
        "A reproduced finding needs concrete reproduction steps; use FAILED for reproduced "
        "MEDIUM/HIGH/CRITICAL defects, PASSED when none, INCONCLUSIVE if unable to assess. "
        "Use an existing repository-relative Python source path in each actionable finding. "
        "Do not claim a test ran unless you ran it."
    )
    message = Message(
        protocol="ACP", version="0.1", message_id=str(uuid4()), run_id=run_id,
        task_id="maintenance-scan", sender=orchestrator.agent_id,
        recipient=qa.agent_id, type=MessageType.REVIEW_REQUEST, iteration=1,
        created_at=datetime.now(timezone.utc),
        payload=ReviewRequest(artifact_id=f"{run_id}-baseline", criteria=prompt),
        metadata={"engineering_run_id": run_id},
    )
    broker.publish(message, orchestrator)
    result = await manager.execute(ExecutionRequest(
        execution_id=str(uuid4()), run_id=run_id, task_id="maintenance-scan",
        agent_id=qa.agent_id, executor="codex", prompt=prompt,
        working_directory=qa_path, sandbox_mode="read-only", timeout_seconds=600,
    ), qa, message.message_id)
    if result.status != ExecutionStatus.SUCCEEDED:
        with broker.db.connect() as db:
            db.execute("UPDATE maintenance_scan SET status=? WHERE run_id=?", ("SCAN_FAILED", run_id))
        print(json.dumps({"run_id": run_id, "status": "SCAN_FAILED", "error": result.error}))
        return 1
    review = QAReviewResult.model_validate_json(result.output)
    if review.task_id != "maintenance-scan" or review.iteration != 1 or review.reviewed_commit != base:
        raise ValueError("QA review does not match the scanned baseline")
    findings = [item for item in review.findings if item.status == "REPRODUCED"]
    allowed = tuple(sorted({item.file for item in findings if item.file
                            and (source / item.file).is_file()
                            and (source / item.file).resolve().is_relative_to(source)
                            and item.file.endswith(".py")
                            and not Path(item.file).name.startswith("test_")}))
    baseline_gates = (
        run_gates(source, base, (GATE,), policy=policy)
        if review.review_status == "PASSED" and not findings else []
    )
    status = scan_status(review, baseline_gates)
    with broker.db.connect() as db:
        db.execute("UPDATE maintenance_scan SET status=?,review=?,gate_result=? WHERE run_id=?",
                   (status, review.model_dump_json(),
                    json.dumps([gate.model_dump(mode="json") for gate in baseline_gates]), run_id))
    if status == "NO_CHANGES" or review.review_status != "FAILED" or not allowed:
        print(json.dumps({"run_id": run_id, "status": status, "findings": len(findings),
                          "database": str(root / "aec.sqlite")}))
        return 0 if status == "NO_CHANGES" else 1
    specification = (
        "Correct only these reproduced defects of logic or efficiency, preserving each module's "
        "intended behavior and public API. Do not add features or edit other files. "
        + review.model_dump_json()
    )
    loop = AdversarialLoop(
        broker, manager, orchestrator, implementer, qa, quality_gate,
        source, worktrees, (GATE,), max_iterations=3,
        local_approvers=frozenset({"local-supervisor"}),
    )
    loop.create("maintenance-scan", specification, (
        "Fix each reproduced defect without adding functionality",
        "Independent QA checks the original contract and regression risk",
        "QA uses INCONCLUSIVE only with a stated limitation that prevents a decision",
        "Database tests run in the controller's deterministic gate; QA sandbox network isolation "
        "alone does not make code review inconclusive",
        "Existing tests pass",
    ), allowed, run_id=run_id)
    status = await loop.run(run_id)
    with broker.db.connect() as db:
        db.execute("UPDATE maintenance_scan SET status=? WHERE run_id=?", (status, run_id))
    print(json.dumps({"run_id": run_id, "status": status, "findings": len(findings),
                      "database": str(root / "aec.sqlite")}))
    return 0 if status == "WAITING_APPROVAL" else 1


def report(run_id: str) -> None:
    run_id = str(UUID(run_id))
    database = RUNS / run_id / "aec.sqlite"
    if not database.is_file():
        raise FileNotFoundError(database)
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        run = connection.execute(
            "SELECT run_id,status,base_commit,head_commit,worktree_path,error "
            "FROM engineering_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        scan_row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_scan'"
        ).fetchone()
        scan = connection.execute(
            "SELECT * FROM maintenance_scan WHERE run_id=?",
            (run_id,),
        ).fetchone() if scan_row else None
        if run is None and scan is None:
            raise KeyError(run_id)
        iterations = [{
            "number": row["number"],
            "status": row["status"],
            "review": json.loads(row["review"]) if row["review"] else None,
            "gates": json.loads(row["gates"]) if row["gates"] else None,
        } for row in connection.execute(
            "SELECT number,status,review,gates FROM engineering_iterations WHERE run_id=? ORDER BY number",
            (run_id,),
        )]
        approval = connection.execute(
            "SELECT status,decided_by FROM workflow_approvals WHERE run_id=?",
            (f"{run_id}-approval",),
        ).fetchone()
    print(json.dumps({
        "run": dict(run) if run else None,
        "scan": ({**dict(scan),
                  "review": json.loads(scan["review"]) if scan["review"] else None,
                  **({"gate_result": json.loads(scan["gate_result"])}
                     if "gate_result" in scan.keys() and scan["gate_result"] else {})}
                 if scan else None),
        "iterations": iterations,
        "approval": dict(approval) if approval else None,
        "database": str(database),
    }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("start")
    commands.add_parser("scan")
    commands.add_parser("report").add_argument("run_id")
    args = parser.parse_args()
    if args.command == "start":
        return asyncio.run(start())
    if args.command == "scan":
        return asyncio.run(scan())
    report(args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
