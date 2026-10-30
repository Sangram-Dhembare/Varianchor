# VeriAnchor

VeriAnchor is a local-first tool for checking the integrity of batches of
records. The goal is to create a signed batch, build a Merkle proof for each
record, and verify the batch root locally or against a local EVM chain.

The project is being built in stages. The backend now creates persistent local
batches, builds sorted-pair Keccak-256 Merkle roots and per-record proofs, and
verifies submitted records against a saved batch. The contract and dashboard
will follow as they are implemented and tested.

## Design goals

- Run locally without hosted services or API keys.
- Keep batch data in a local SQLite database.
- Use the same sorted-pair Keccak-256 format in Python and Solidity.
- Make it straightforward to inspect a proof and see whether a record was
  changed.

The planned stack is Solidity with Hardhat, a FastAPI backend, and a
React/TypeScript dashboard. Development chain traffic will use the local
Hardhat JSON-RPC endpoint at `http://127.0.0.1:8545`.

## Development status

This is an early-stage project. Features will be added in small, verifiable
steps; the README will be updated as each part is ready to use.

The FastAPI service is in `backend/app/main.py`; SQLite data is stored at
`~/.verianchor/verianchor.sqlite3` by default. Override the database location
with `VERIANCHOR_DB_PATH`. Install dependencies with
`python3 -m pip install -r backend/requirements.txt`, run the API locally with
`uvicorn app.main:app --app-dir backend --reload`, and run tests with
`python3 -m unittest discover -s backend/tests -t backend`.

The API exposes `POST /batches`, `GET /batches/{id}`,
`GET /batches/{id}/proof/{index}`, and `POST /batches/{id}/verify`.
