from __future__ import annotations
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from .base import (
    StatefulConnector, StateCheckResult, ConfirmationResult, ConnectorResult,
    ExecutionMode, _logger,
)
from .state_store import StateStore


class DatabaseConnector(StatefulConnector):
    """Three-phase database connector.

    MOCK  → reads/writes StateStore (no real DB).
    SANDBOX/LIVE → reads/writes real SQLite.
    """

    ALLOWED_ROLES_DELETE = frozenset({"admin", "dpo", "data_protection_officer"})
    ALLOWED_ROLES_READ = frozenset({
        "admin", "analyst", "manager", "ops_manager", "viewer", "customer",
    })
    ALLOWED_TABLES = frozenset({
        "user_data", "transactions", "accounts", "audit_log",
    })

    def __init__(
        self, mode: ExecutionMode = ExecutionMode.MOCK,
        db_path: Optional[str] = None,
        state_store: Optional[StateStore] = None,
    ) -> None:
        self._mode = mode
        self._store = state_store or StateStore()
        self._db_path = db_path or os.environ.get(
            "DATABASE_URL", "sqlite:///signalweaver.db",
        ).replace("sqlite:///", "")
        self._lock = threading.Lock()
        if self._mode != ExecutionMode.MOCK:
            self._init_db()

    @property
    def _is_real(self) -> bool:
        return self._mode != ExecutionMode.MOCK

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        try:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    data_value TEXT,
                    created_at INTEGER NOT NULL,
                    deleted_at INTEGER,
                    version INTEGER DEFAULT 1,
                    UNIQUE(user_id, data_type)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sw_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    action TEXT,
                    table_name TEXT,
                    details TEXT,
                    executed_at INTEGER NOT NULL
                )
            """)
            conn.commit()
            conn.close()
        except Exception as exc:
            _logger.error("DB init failed: %s", exc)

    # -- Phase 1: PRECHECK --

    def precheck(self, trusted_context: Dict[str, Any]) -> StateCheckResult:
        user_id = trusted_context.get("user_id", "")
        data_type = trusted_context.get("data_type", "")
        table = trusted_context.get("table_name", data_type)
        ts = int(time.time() * 1000)

        if table not in self.ALLOWED_TABLES:
            return StateCheckResult(
                False, {},
                [f"table_not_allowed: {table}"],
                None, ts, "database",
            )

        if self._is_real:
            return self._precheck_real(table, user_id, data_type, ts)
        return self._precheck_mock(table, user_id, data_type, ts)

    def _precheck_mock(
        self, table: str, user_id: str, data_type: str, ts: int,
    ) -> StateCheckResult:
        record = self._store.get_record(table, user_id, data_type)
        if record is None:
            return StateCheckResult(
                False, {},
                [f"record_not_found: {table}/{user_id}/{data_type}"],
                None, ts, "database",
            )
        violations = []
        if not record["exists"]:
            violations.append("record_does_not_exist")
        if record["deleted"]:
            violations.append("record_already_deleted")

        observed = {
            "table": table, "user_id": user_id, "data_type": data_type,
            "exists": record["exists"], "deleted": record["deleted"],
            "deleted_at": record.get("deleted_at"),
        }
        return StateCheckResult(
            len(violations) == 0, observed, violations,
            str(record["version"]), ts, "database",
        )

    def _precheck_real(
        self, table: str, user_id: str, data_type: str, ts: int,
    ) -> StateCheckResult:
        try:
            with self._lock:
                conn = self._get_conn()
                row = conn.execute(
                    "SELECT user_id, data_type, data_value, created_at, "
                    "deleted_at, version FROM user_data "
                    "WHERE user_id = ? AND data_type = ?",
                    (user_id, data_type),
                ).fetchone()
                conn.close()
        except Exception as exc:
            return StateCheckResult(
                False, {}, [f"db_read_failed: {exc}"],
                None, ts, "database",
            )

        if row is None:
            return StateCheckResult(
                False, {},
                [f"record_not_found: {table}/{user_id}/{data_type}"],
                None, ts, "database",
            )

        row_dict = dict(row)
        violations = []
        if row_dict["deleted_at"] is not None:
            violations.append("record_already_deleted")

        return StateCheckResult(
            len(violations) == 0, row_dict, violations,
            str(row_dict.get("version", 0)), ts, "database",
        )

    # -- Phase 2: EXECUTE --

    def execute(self, trusted_context: Dict[str, Any],
                idempotency_key: str, trace_id: str,
                pre_state_check: Optional[StateCheckResult] = None) -> ConnectorResult:
        ts = int(time.time() * 1000)
        is_live = self._mode == ExecutionMode.LIVE
        action = trusted_context.get("_data_action", "QUERY")
        role = trusted_context.get("role", "unknown")
        table = trusted_context.get("table_name",
                                    trusted_context.get("data_type", "user_data"))

        if table not in self.ALLOWED_TABLES:
            return ConnectorResult(
                "blocked", None, "database", ts, trace_id, is_live,
                {"error": f"table_not_allowed: {table}"},
            )

        if action == "DELETE" and role not in self.ALLOWED_ROLES_DELETE:
            return ConnectorResult(
                "blocked", None, "database", ts, trace_id, is_live,
                {"error": f"role_not_authorised_for_delete: {role}"},
            )

        if action == "DELETE":
            if self._is_real:
                return self._execute_delete_real(
                    table, trusted_context, trace_id, ts, is_live, pre_state_check)
            return self._execute_delete_mock(table, trusted_context, trace_id, ts)

        return ConnectorResult(
            "success", None, "database", ts, trace_id, is_live,
            {"action": action, "table": table, "note": "read-only in this delta"},
        )

    def _execute_delete_mock(
        self, table: str, ctx: Dict[str, Any],
        trace_id: str, ts: int,
    ) -> ConnectorResult:
        user_id = ctx.get("user_id", "")
        data_type = ctx.get("data_type", "")
        ok = self._store.mark_deleted(table, user_id, data_type)
        if not ok:
            return ConnectorResult(
                "failed", None, "database_mock", ts, trace_id, False,
                {"error": "mark_deleted_returned_false",
                 "table": table, "user_id": user_id},
            )
        return ConnectorResult(
            "success", f"del_mock_{uuid.uuid4().hex[:10]}",
            "database_mock", ts, trace_id, False,
            {"action": "soft_delete", "table": table, "user_id": user_id},
        )

    def _execute_delete_real(
        self, table: str, ctx: Dict[str, Any],
        trace_id: str, ts: int, is_live: bool,
        pre_state_check: Optional[StateCheckResult] = None,
    ) -> ConnectorResult:
        user_id = ctx.get("user_id", "")
        data_type = ctx.get("data_type", "")
        external_op_id = f"db_op_{uuid.uuid4().hex}"
        try:
            with self._lock:
                conn = self._get_conn()
                # Optimistic concurrency: include version in WHERE clause
                if pre_state_check and pre_state_check.state_version is not None:
                    params = (ts, user_id, data_type, int(pre_state_check.state_version))
                    cursor = conn.execute(
                        "UPDATE user_data SET deleted_at = ?, version = version + 1 "
                        "WHERE user_id = ? AND data_type = ? AND deleted_at IS NULL "
                        "AND version = ?",
                        params,
                    )
                else:
                    cursor = conn.execute(
                        "UPDATE user_data SET deleted_at = ?, version = version + 1 "
                        "WHERE user_id = ? AND data_type = ? AND deleted_at IS NULL",
                        (ts, user_id, data_type),
                    )
                affected = cursor.rowcount
                conn.execute(
                    "INSERT INTO sw_audit_log (trace_id, phase, action, table_name, details, executed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (trace_id, "execute", "SOFT_DELETE", table,
                     json.dumps({"user_id": user_id, "data_type": data_type,
                                 "affected": affected, "external_op_id": external_op_id}),
                     ts),
                )
                conn.commit()
                conn.close()
            if affected == 0:
                if pre_state_check and pre_state_check.state_version is not None:
                    error_key = "optimistic_lock_failed"
                else:
                    error_key = "no_rows_affected"
                return ConnectorResult(
                    "failed", None, "database", ts, trace_id, is_live,
                    {"error": error_key, "user_id": user_id},
                )
            return ConnectorResult(
                "success", external_op_id, "database", ts, trace_id, is_live,
                {"action": "soft_delete", "affected_rows": affected,
                 "table": table, "user_id": user_id, "external_op_id": external_op_id},
            )
        except Exception as exc:
            return ConnectorResult(
                "failed", None, "database", ts, trace_id, is_live,
                {"error": f"db_delete_failed: {exc}"},
            )

    # -- Phase 3: CONFIRM --

    def confirm(self, trusted_context: Dict[str, Any],
                connector_result: ConnectorResult,
                pre_state_check: StateCheckResult) -> ConfirmationResult:
        ts = int(time.time() * 1000)

        if connector_result.status == "blocked":
            return ConfirmationResult(
                False, "connector_blocked",
                {"connector_status": "blocked"},
                [f"connector_status_not_success: blocked"],
                ts,
            )

        if connector_result.status == "failed":
            # Attempt confirm read anyway for audit purposes
            user_id = trusted_context.get("user_id", "")
            data_type = trusted_context.get("data_type", "")
            table = trusted_context.get("table_name", data_type)
            return self._confirm_audit_read(table, user_id, data_type, connector_result, ts)

        user_id = trusted_context.get("user_id", "")
        data_type = trusted_context.get("data_type", "")
        table = trusted_context.get("table_name", data_type)

        if self._is_real:
            return self._confirm_real(
                table, user_id, data_type, pre_state_check, ts)
        return self._confirm_mock(
            table, user_id, data_type, pre_state_check, ts)

    def _confirm_mock(
        self, table: str, user_id: str, data_type: str,
        pre_state_check: StateCheckResult, ts: int,
    ) -> ConfirmationResult:
        record = self._store.get_record(table, user_id, data_type)
        if record is None:
            return ConfirmationResult(
                False, "direct_read",
                {"record_found": False},
                ["record_disappeared_after_delete"], ts,
            )

        discrepancies = []
        if not record["deleted"]:
            discrepancies.append("record_not_marked_deleted_after_operation")

        # Version check
        pre_version = pre_state_check.state_version
        current_version = str(record["version"])
        if pre_version is not None:
            expected = str(int(pre_version) + 1)
            if current_version != expected:
                discrepancies.append(
                    f"version_mismatch: expected={expected} actual={current_version}"
                )

        source = "direct_read" if not discrepancies else "direct_read_with_discrepancies"
        return ConfirmationResult(
            len(discrepancies) == 0, source,
            {"table": table, "user_id": user_id, "data_type": data_type,
             "deleted": record["deleted"], "version": record["version"]},
            discrepancies, ts,
        )

    def _confirm_audit_read(
        self, table: str, user_id: str, data_type: str,
        connector_result: ConnectorResult, ts: int,
    ) -> ConfirmationResult:
        """Read external state after connector failure for audit trail."""
        if self._is_real:
            try:
                with self._lock:
                    conn = self._get_conn()
                    row = conn.execute(
                        "SELECT user_id, data_type, deleted_at, version "
                        "FROM user_data WHERE user_id = ? AND data_type = ?",
                        (user_id, data_type),
                    ).fetchone()
                    conn.close()
                if row is None:
                    observed = {"record_found": False, "audit_read_after_failure": True}
                else:
                    rd = dict(row)
                    observed = {
                        "user_id": rd["user_id"], "data_type": rd["data_type"],
                        "deleted_at": rd["deleted_at"], "version": rd["version"],
                        "audit_read_after_failure": True,
                    }
                return ConfirmationResult(
                    False, "audit_read_after_failure",
                    observed,
                    [f"connector_failed: {connector_result.details.get('error', 'unknown')}"],
                    ts,
                )
            except Exception as exc:
                return ConfirmationResult(
                    False, "audit_read_failed",
                    {"error": str(exc), "audit_read_after_failure": True},
                    [f"connector_failed_and_read_error: {exc}"],
                    ts, read_failed=True,
                )
        # MOCK: read StateStore for audit
        record = self._store.get_record(table, user_id, data_type)
        if record is None:
            observed = {"record_found": False, "audit_read_after_failure": True}
        else:
            observed = {
                "table": table, "user_id": user_id, "data_type": data_type,
                "deleted": record["deleted"], "version": record["version"],
                "audit_read_after_failure": True,
            }
        return ConfirmationResult(
            False, "audit_read_after_failure",
            observed,
            [f"connector_failed: {connector_result.details.get('error', 'unknown')}"],
            ts,
        )

    def _confirm_real(
        self, table: str, user_id: str, data_type: str,
        pre_state_check: StateCheckResult, ts: int,
    ) -> ConfirmationResult:
        try:
            with self._lock:
                conn = self._get_conn()
                row = conn.execute(
                    "SELECT user_id, data_type, deleted_at, version "
                    "FROM user_data WHERE user_id = ? AND data_type = ?",
                    (user_id, data_type),
                ).fetchone()
                conn.close()
        except Exception as exc:
            return ConfirmationResult(
                False, "direct_read_error",
                {"error": str(exc)},
                [f"db_read_failed_during_confirm: {exc}"], ts,
            )

        if row is None:
            return ConfirmationResult(
                False, "direct_read",
                {"record_found": False},
                ["record_disappeared_after_delete"], ts,
            )

        row_dict = dict(row)
        discrepancies = []
        if row_dict["deleted_at"] is None:
            discrepancies.append("record_not_marked_deleted_after_operation")

        pre_version = pre_state_check.state_version
        current_version = str(row_dict.get("version", 0))
        if pre_version is not None:
            expected = str(int(pre_version) + 1)
            if current_version != expected:
                discrepancies.append(
                    f"version_mismatch: expected={expected} actual={current_version}"
                )

        source = "direct_read" if not discrepancies else "direct_read_with_discrepancies"
        return ConfirmationResult(
            len(discrepancies) == 0, source,
            {"table": table, "user_id": user_id,
             "deleted_at": row_dict["deleted_at"],
             "version": row_dict["version"]},
            discrepancies, ts,
        )

    def health_check(self) -> Dict[str, Any]:
        if self._mode == ExecutionMode.MOCK:
            return {"connector": "database", "mode": "MOCK", "status": "ready"}
        try:
            conn = self._get_conn()
            conn.execute("SELECT 1")
            conn.close()
            return {"connector": "database", "mode": self._mode.value,
                    "db_path": self._db_path, "status": "ready"}
        except Exception as exc:
            return {"connector": "database", "mode": self._mode.value,
                    "status": "error", "error": str(exc)}
