import os
from pathlib import Path
from typing import Sequence

from eth_hash.auto import keccak


def canonical_record(record: object) -> str:
    import json

    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_leaf(record: bytes) -> bytes:
    return keccak(record)


def hash_pair(left: bytes, right: bytes) -> bytes:
    if len(left) != 32 or len(right) != 32:
        raise ValueError("Merkle nodes must be 32 bytes")
    first, second = sorted((left, right))
    return keccak(first + second)


def build_merkle_tree(records: Sequence[bytes]) -> tuple[bytes, list[list[bytes]]]:
    if not records:
        raise ValueError("At least one record is required")

    levels = [[hash_leaf(record) for record in records]]
    while len(levels[-1]) > 1:
        current = levels[-1]
        next_level = [
            hash_pair(current[index], current[min(index + 1, len(current) - 1)])
            for index in range(0, len(current), 2)
        ]
        levels.append(next_level)

    proofs = []
    for leaf_index in range(len(records)):
        proof = []
        index = leaf_index
        for level in levels[:-1]:
            sibling_index = index ^ 1
            proof.append(level[min(sibling_index, len(level) - 1)])
            index //= 2
        proofs.append(proof)

    return levels[-1][0], proofs


def verify_proof(record: bytes, proof: Sequence[bytes], root: bytes) -> bool:
    if len(root) != 32 or any(len(node) != 32 for node in proof):
        raise ValueError("Merkle roots and proof nodes must be 32 bytes")

    value = hash_leaf(record)
    for sibling in proof:
        value = hash_pair(value, sibling)
    return value == root


def sign_root(root: bytes, private_key: str) -> tuple[str, str]:
    from eth_account import Account
    from eth_account.messages import encode_defunct

    if len(root) != 32:
        raise ValueError("Merkle roots must be 32 bytes")
    message = encode_defunct(text="VeriAnchor batch root: 0x" + root.hex())
    signed = Account.sign_message(message, private_key=private_key)
    signature = signed["signature"].hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    return Account.from_key(private_key).address, signature


def verify_root_signature(root: bytes, signer: str, signature: str) -> bool:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from eth_keys.exceptions import BadSignature
    from eth_utils.exceptions import ValidationError

    if len(root) != 32:
        raise ValueError("Merkle roots must be 32 bytes")
    message = encode_defunct(text="VeriAnchor batch root: 0x" + root.hex())
    try:
        recovered = Account.recover_message(message, signature=signature)
    except (BadSignature, IndexError, TypeError, ValidationError, ValueError):
        return False
    return recovered.lower() == signer.lower()


def load_or_create_signing_key(key_path: str) -> str:
    from eth_account import Account

    path = Path(key_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
    except FileExistsError:
        key = path.read_text(encoding="ascii").strip()
        Account.from_key(key)
        path.chmod(0o600)
        return key

    key = Account.create().key.hex()
    with os.fdopen(descriptor, "w", encoding="ascii") as key_file:
        key_file.write(key + "\n")
    return key
