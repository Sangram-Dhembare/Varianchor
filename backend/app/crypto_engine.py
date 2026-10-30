from typing import Sequence

from eth_hash.auto import keccak


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
