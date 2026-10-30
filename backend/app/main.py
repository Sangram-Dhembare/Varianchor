import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.crypto_engine import build_merkle_tree, verify_proof
from app.database import BatchStore, encode_record


class CreateBatchRequest(BaseModel):
    records: list[Any] = Field(min_length=1, max_length=1000)


class VerifyRecordRequest(BaseModel):
    index: int = Field(ge=0)
    record: Any


def create_app(database_path: Optional[str] = None) -> FastAPI:
    if database_path is None:
        database_path = os.environ.get(
            "VERIANCHOR_DB_PATH",
            str(Path.home() / ".verianchor" / "verianchor.sqlite3"),
        )
    store = BatchStore(database_path)
    app = FastAPI(title="VeriAnchor API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/batches", status_code=201)
    def create_batch(request: CreateBatchRequest) -> dict[str, Any]:
        return store.create_batch(request.records)

    @app.get("/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        batch = store.get_batch(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        return batch

    @app.get("/batches/{batch_id}/proof/{index}")
    def get_proof(batch_id: str, index: int) -> dict[str, Any]:
        batch = store.get_batch(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        records = store.get_records(batch_id)
        if records is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        if index < 0 or index >= batch["record_count"]:
            raise HTTPException(status_code=404, detail="Record index not found")

        decoded_records = [json.loads(record) for record in records]
        _, proofs = build_merkle_tree([record.encode("utf-8") for record in records])
        return {
            "batch_id": batch_id,
            "index": index,
            "record": decoded_records[index],
            "proof": [node.hex() for node in proofs[index]],
            "root": batch["root"],
        }

    @app.post("/batches/{batch_id}/verify")
    def verify_record(batch_id: str, request: VerifyRecordRequest) -> dict[str, Any]:
        batch = store.get_batch(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        records = store.get_records(batch_id)
        if records is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        if request.index >= batch["record_count"]:
            raise HTTPException(status_code=404, detail="Record index not found")

        _, proofs = build_merkle_tree([record.encode("utf-8") for record in records])
        record_bytes = encode_record(request.record).encode("utf-8")
        valid = verify_proof(
            record_bytes,
            proofs[request.index],
            bytes.fromhex(batch["root"]),
        )
        return {
            "batch_id": batch_id,
            "index": request.index,
            "valid": valid,
            "root": batch["root"],
        }

    return app


app = create_app()
