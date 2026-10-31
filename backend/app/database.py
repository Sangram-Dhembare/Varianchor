import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

from app.crypto_engine import (
    build_merkle_tree,
    canonical_record,
    sign_root,
)


def encode_record(record: Any) -> str:
    return canonical_record(record)


class BatchStore:
    def __init__(self, database_path: str, signing_key: str) -> None:
        self.database_path = (
            database_path
            if database_path == ":memory:"
            else str(Path(database_path).expanduser())
        )
        self.signing_key = signing_key
        if database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY,
                    root TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    signer TEXT,
                    signature TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(batches)")
            }
            if "signer" not in columns:
                connection.execute("ALTER TABLE batches ADD COLUMN signer TEXT")
            if "signature" not in columns:
                connection.execute("ALTER TABLE batches ADD COLUMN signature TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_records (
                    batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY (batch_id, position)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_batch(self, records: Sequence[Any]) -> dict[str, Any]:
        encoded_records = [encode_record(record) for record in records]
        root, _ = build_merkle_tree(
            [record.encode("utf-8") for record in encoded_records]
        )
        signer, signature = sign_root(root, self.signing_key)
        batch = {
            "id": str(uuid.uuid4()),
            "root": root.hex(),
            "record_count": len(encoded_records),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "signer": signer,
            "signature": signature,
        }

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO batches
                    (id, root, record_count, created_at, signer, signature)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    batch["id"],
                    batch["root"],
                    batch["record_count"],
                    batch["created_at"],
                    signer,
                    signature,
                ),
            )
            connection.executemany(
                "INSERT INTO batch_records (batch_id, position, record_json) VALUES (?, ?, ?)",
                [
                    (batch["id"], position, record)
                    for position, record in enumerate(encoded_records)
                ],
            )

        return batch

    def list_batches(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, root, record_count, created_at, signer, signature
                FROM batches ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_batch(self, batch_id: str) -> Optional[dict[str, Any]]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, root, record_count, created_at, signer, signature
                FROM batches WHERE id = ?
                """,
                (batch_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_records(self, batch_id: str) -> Optional[list[str]]:
        with self._connection() as connection:
            batch_exists = connection.execute(
                "SELECT 1 FROM batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if not batch_exists:
                return None
            rows = connection.execute(
                "SELECT record_json FROM batch_records WHERE batch_id = ? ORDER BY position",
                (batch_id,),
            ).fetchall()
        return [row["record_json"] for row in rows]
