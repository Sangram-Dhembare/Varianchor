from typing import Any

from app.crypto_engine import build_merkle_tree, verify_proof
from app.database import BatchStore, encode_record


def demo_records() -> list[dict[str, Any]]:
    return [
        {"event": "invoice.paid", "invoice_id": "INV-1042", "amount_cents": 2450},
        {"event": "invoice.paid", "invoice_id": "INV-1043", "amount_cents": 8900},
        {"event": "invoice.refunded", "invoice_id": "INV-1044", "amount_cents": 1200},
        {"event": "invoice.paid", "invoice_id": "INV-1045", "amount_cents": 5100},
    ]


def create_demo(store: BatchStore) -> dict[str, Any]:
    records = demo_records()
    batch = store.create_batch(records)
    encoded = [encode_record(record).encode("utf-8") for record in records]
    root, proofs = build_merkle_tree(encoded)
    changed = dict(records[1], amount_cents=8901)
    tamper_detected = not verify_proof(
        encode_record(changed).encode("utf-8"), proofs[1], root
    )
    return {
        "batch": batch,
        "records": records,
        "tamper_example": {"index": 1, "original": records[1], "changed": changed},
        "tamper_detected": tamper_detected,
    }
