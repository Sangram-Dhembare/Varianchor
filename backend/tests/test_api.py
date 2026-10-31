import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class BatchApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = str(
            Path(self.temporary_directory.name) / "batches.sqlite3"
        )
        self.app = create_app(self.database_path)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_batch_creation_proof_and_verification(self):
        records = [{"account": "A", "amount": 12}, {"account": "B", "amount": 9}]
        response = self.client.post("/batches", json={"records": records})

        self.assertEqual(response.status_code, 201)
        batch = response.json()
        self.assertEqual(batch["record_count"], 2)
        self.assertEqual(len(batch["root"]), 64)

        proof_response = self.client.get(
            "/batches/{}/proof/0".format(batch["id"])
        )
        self.assertEqual(proof_response.status_code, 200)
        proof = proof_response.json()
        self.assertEqual(proof["record"], records[0])
        self.assertEqual(proof["root"], batch["root"])
        self.assertEqual(len(proof["proof"]), 1)

        valid = self.client.post(
            "/batches/{}/verify".format(batch["id"]),
            json={"index": 0, "record": records[0]},
        )
        tampered = self.client.post(
            "/batches/{}/verify".format(batch["id"]),
            json={"index": 0, "record": {"account": "A", "amount": 13}},
        )
        self.assertTrue(valid.json()["valid"])
        self.assertFalse(tampered.json()["valid"])

    def test_batch_has_a_valid_signature_and_is_listed(self):
        created = self.client.post(
            "/batches", json={"records": [{"item": "signed"}]}
        ).json()

        details = self.client.get("/batches/{}".format(created["id"])).json()
        listed = self.client.get("/batches").json()["batches"]

        self.assertTrue(details["signature_valid"])
        self.assertTrue(details["signer"].startswith("0x"))
        self.assertTrue(details["signature"].startswith("0x"))
        self.assertEqual(listed[0]["id"], created["id"])

    def test_proof_includes_a_smart_contract_ready_leaf(self):
        batch = self.client.post("/batches", json={"records": ["proof"]}).json()

        proof = self.client.get(
            "/batches/{}/proof/0".format(batch["id"])
        ).json()

        self.assertEqual(len(proof["leaf"]), 64)
        self.assertEqual(proof["root"], batch["root"])

    def test_demo_endpoint_returns_a_tamper_example(self):
        response = self.client.post("/demo")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["tamper_detected"])

    def test_changed_saved_records_cannot_produce_a_misleading_proof(self):
        batch = self.client.post(
            "/batches", json={"records": [{"item": "original"}]}
        ).json()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE batch_records SET record_json = ? WHERE batch_id = ?",
                (json.dumps({"item": "changed"}, separators=(",", ":")), batch["id"]),
            )

        response = self.client.get(
            "/batches/{}/proof/0".format(batch["id"])
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("no longer match", response.json()["detail"])

    def test_invalid_signature_is_rejected_before_anchoring(self):
        batch = self.client.post(
            "/batches", json={"records": [{"item": "signed"}]}
        ).json()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE batches SET signature = ? WHERE id = ?",
                ("malformed-signature", batch["id"]),
            )

        self.assertFalse(
            self.client.get("/batches/{}".format(batch["id"])).json()[
                "signature_valid"
            ]
        )
        response = self.client.post(
            "/batches/{}/anchor".format(batch["id"])
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("signature is invalid", response.json()["detail"])

    def test_batch_survives_app_restart(self):
        response = self.client.post("/batches", json={"records": ["persistent"]})
        batch_id = response.json()["id"]
        database_path = str(Path(self.temporary_directory.name) / "batches.sqlite3")

        restarted_client = TestClient(create_app(database_path))

        self.assertEqual(
            restarted_client.get("/batches/{}".format(batch_id)).status_code, 200
        )

    def test_invalid_batch_and_record_indices_are_rejected(self):
        self.assertEqual(self.client.get("/batches/missing").status_code, 404)
        self.assertEqual(
            self.client.post("/batches", json={"records": []}).status_code, 422
        )

        batch = self.client.post("/batches", json={"records": ["only"]}).json()
        self.assertEqual(
            self.client.get("/batches/{}/proof/1".format(batch["id"])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/batches/{}/verify".format(batch["id"]),
                json={"index": 1, "record": "outside"},
            ).status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
