import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.chain_client import ChainClient, ChainUnavailable
from app.crypto_engine import (
    build_merkle_tree,
    hash_leaf,
    load_or_create_signing_key,
    verify_proof,
    verify_root_signature,
)
from app.database import BatchStore, encode_record
from app.simulator import create_demo


class CreateBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[Any] = Field(min_length=1, max_length=1000)


class VerifyRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    record: Any


def create_app(database_path: Optional[str] = None) -> FastAPI:
    if database_path is None:
        database_path = os.environ.get(
            "VERIANCHOR_DB_PATH",
            str(Path.home() / ".verianchor" / "verianchor.sqlite3"),
        )
    if database_path == ":memory:":
        default_key_path = str(Path.home() / ".verianchor" / "signing.key")
    else:
        default_key_path = str(Path(database_path).expanduser().parent / "signing.key")
    key_path = os.environ.get("VERIANCHOR_SIGNING_KEY_FILE", default_key_path)
    signing_key = os.environ.get("VERIANCHOR_SIGNING_KEY")
    if signing_key is None:
        signing_key = load_or_create_signing_key(key_path)

    store = BatchStore(database_path, signing_key)
    app = FastAPI(
        title="VeriAnchor API",
        description="Local batch integrity, signature, and Merkle proof service.",
        version="1.0.0",
    )
    allowed_origins = os.environ.get(
        "VERIANCHOR_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in allowed_origins.split(",")],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def batch_records(batch_id: str) -> tuple[dict[str, Any], list[str]]:
        batch = store.get_batch(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        records = store.get_records(batch_id)
        if records is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        return batch, records

    def stored_merkle_tree(
        batch: dict[str, Any], records: list[str]
    ) -> tuple[list[bytes], bytes, list[list[bytes]]]:
        encoded_records = [record.encode("utf-8") for record in records]
        root, proofs = build_merkle_tree(encoded_records)
        if root.hex() != batch["root"]:
            raise HTTPException(
                status_code=409,
                detail="Stored records no longer match the saved batch root",
            )
        return encoded_records, root, proofs

    def has_valid_signature(batch: dict[str, Any]) -> bool:
        signer = batch.get("signer")
        signature = batch.get("signature")
        return bool(
            signer
            and signature
            and verify_root_signature(
                bytes.fromhex(batch["root"]), signer, signature
            )
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/chain/status")
    def chain_status() -> dict[str, Any]:
        try:
            return ChainClient.from_environment().status()
        except ChainUnavailable as error:
            return {"connected": False, "error": str(error)}

    @app.get("/batches")
    def list_batches(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"batches": store.list_batches(limit)}

    @app.post("/batches", status_code=201)
    def create_batch(request: CreateBatchRequest) -> dict[str, Any]:
        return store.create_batch(request.records)

    @app.post("/demo", status_code=201)
    def create_demo_batch() -> dict[str, Any]:
        return create_demo(store)

    @app.get("/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        batch = store.get_batch(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        batch["signature_valid"] = has_valid_signature(batch)
        return batch

    @app.get("/batches/{batch_id}/proof/{index}")
    def get_proof(batch_id: str, index: int) -> dict[str, Any]:
        batch, records = batch_records(batch_id)
        if index < 0 or index >= batch["record_count"]:
            raise HTTPException(status_code=404, detail="Record index not found")

        decoded_records = [json.loads(record) for record in records]
        encoded_records, _, proofs = stored_merkle_tree(batch, records)
        return {
            "batch_id": batch_id,
            "index": index,
            "record": decoded_records[index],
            "leaf": hash_leaf(encoded_records[index]).hex(),
            "proof": [node.hex() for node in proofs[index]],
            "root": batch["root"],
        }

    @app.post("/batches/{batch_id}/verify")
    def verify_record(batch_id: str, request: VerifyRecordRequest) -> dict[str, Any]:
        batch, records = batch_records(batch_id)
        if request.index >= batch["record_count"]:
            raise HTTPException(status_code=404, detail="Record index not found")

        _, _, proofs = stored_merkle_tree(batch, records)
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

    @app.post("/batches/{batch_id}/anchor")
    def anchor_batch(batch_id: str) -> dict[str, Any]:
        batch = store.get_batch(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        records = store.get_records(batch_id)
        if records is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        stored_merkle_tree(batch, records)
        if not has_valid_signature(batch):
            raise HTTPException(
                status_code=409,
                detail="Batch root signature is invalid; refusing to anchor it",
            )
        try:
            result = ChainClient.from_environment().anchor_root(
                bytes.fromhex(batch["root"]), batch["record_count"]
            )
        except ChainUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"batch_id": batch_id, "root": batch["root"], **result}

    @app.post("/batches/{batch_id}/verify-onchain")
    def verify_record_onchain(
        batch_id: str, request: VerifyRecordRequest
    ) -> dict[str, Any]:
        batch, records = batch_records(batch_id)
        if request.index >= batch["record_count"]:
            raise HTTPException(status_code=404, detail="Record index not found")
        _, _, proofs = stored_merkle_tree(batch, records)
        leaf = hash_leaf(encode_record(request.record).encode("utf-8"))
        proof = proofs[request.index]
        root = bytes.fromhex(batch["root"])
        try:
            chain = ChainClient.from_environment()
            anchored = chain.is_anchored(root)
            valid = anchored and chain.verify_proof(leaf, proof, root)
        except ChainUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {
            "batch_id": batch_id,
            "index": request.index,
            "anchored": anchored,
            "valid": valid,
            "root": batch["root"],
        }

    return app


app = create_app()
