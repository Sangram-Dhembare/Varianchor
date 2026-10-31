import unittest

from eth_account import Account

from app.crypto_engine import (
    build_merkle_tree,
    hash_leaf,
    sign_root,
    verify_proof,
    verify_root_signature,
)


class MerkleTreeTests(unittest.TestCase):
    def test_builds_and_verifies_proofs_for_odd_number_of_records(self):
        records = [b"alpha", b"beta", b"gamma"]
        root, proofs = build_merkle_tree(records)

        self.assertEqual(len(root), 32)
        self.assertEqual(len(proofs), len(records))
        for record, proof in zip(records, proofs):
            self.assertTrue(verify_proof(record, proof, root))

    def test_proof_fails_for_a_changed_record(self):
        root, proofs = build_merkle_tree([b"original", b"other"])

        self.assertFalse(verify_proof(b"changed", proofs[0], root))

    def test_single_record_has_an_empty_proof(self):
        record = b"single"
        root, proofs = build_merkle_tree([record])

        self.assertEqual(root, hash_leaf(record))
        self.assertEqual(proofs, [[]])
        self.assertTrue(verify_proof(record, proofs[0], root))

    def test_empty_tree_is_rejected(self):
        with self.assertRaises(ValueError):
            build_merkle_tree([])

    def test_root_signature_can_be_verified_and_rejects_another_root(self):
        account = Account.create()
        root, _ = build_merkle_tree([b"signed"])
        signer, signature = sign_root(root, account.key.hex())

        self.assertEqual(signer.lower(), account.address.lower())
        self.assertTrue(verify_root_signature(root, signer, signature))
        self.assertFalse(
            verify_root_signature(hash_leaf(b"other"), signer, signature)
        )


if __name__ == "__main__":
    unittest.main()
