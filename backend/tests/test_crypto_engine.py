import unittest

from app.crypto_engine import build_merkle_tree, hash_leaf, verify_proof


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


if __name__ == "__main__":
    unittest.main()
