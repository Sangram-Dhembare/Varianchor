import json
import os
from pathlib import Path
from typing import Any, Optional, Sequence


REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "root", "type": "bytes32"},
                   {"internalType": "uint64", "name": "leafCount", "type": "uint64"}],
        "name": "anchorRoot",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "root", "type": "bytes32"}],
        "name": "anchors",
        "outputs": [
            {"internalType": "address", "name": "submitter", "type": "address"},
            {"internalType": "uint64", "name": "anchoredAt", "type": "uint64"},
            {"internalType": "uint64", "name": "leafCount", "type": "uint64"},
            {"internalType": "bool", "name": "exists", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "leaf", "type": "bytes32"},
            {"internalType": "bytes32[]", "name": "proof", "type": "bytes32[]"},
            {"internalType": "bytes32", "name": "root", "type": "bytes32"},
        ],
        "name": "verifyProof",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class ChainUnavailable(RuntimeError):
    pass


class ChainClient:
    def __init__(
        self,
        rpc_url: str,
        contract_address: str,
        timeout: int = 3,
    ) -> None:
        from requests.exceptions import RequestException
        from web3 import Web3
        from web3.exceptions import Web3Exception

        self.web3 = Web3(
            Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout})
        )
        try:
            connected = self.web3.is_connected()
        except (RequestException, Web3Exception) as error:
            raise ChainUnavailable(
                "Cannot connect to the configured JSON-RPC node"
            ) from error
        if not connected:
            raise ChainUnavailable("Cannot connect to the configured JSON-RPC node")
        try:
            address = Web3.to_checksum_address(contract_address)
            self.contract = self.web3.eth.contract(
                address=address, abi=REGISTRY_ABI
            )
            if self.web3.eth.get_code(address) in (b"", b"\x00"):
                raise ChainUnavailable("No contract is deployed at the configured address")
        except (ValueError, RequestException, Web3Exception) as error:
            raise ChainUnavailable("Invalid contract address or RPC response") from error
        self.contract_address = address

    @classmethod
    def from_environment(cls) -> "ChainClient":
        rpc_url = os.environ.get("VERIANCHOR_RPC_URL", "http://127.0.0.1:8545")
        address = os.environ.get("VERIANCHOR_CONTRACT_ADDRESS")
        address_file = os.environ.get("VERIANCHOR_CONTRACT_ADDRESS_FILE")
        if address_file:
            try:
                deployment = json.loads(
                    Path(address_file).expanduser().read_text(encoding="utf-8")
                )
                address = deployment["address"]
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ChainUnavailable(
                    "Contract deployment file is missing or invalid"
                ) from error
        if not address:
            raise ChainUnavailable(
                "Set VERIANCHOR_CONTRACT_ADDRESS after deploying AnchorRegistry"
            )
        return cls(rpc_url, address)

    def status(self) -> dict[str, Any]:
        from requests.exceptions import RequestException
        from web3.exceptions import Web3Exception

        try:
            chain_id = self.web3.eth.chain_id
        except (RequestException, Web3Exception) as error:
            raise ChainUnavailable("Cannot read the local chain status") from error
        return {
            "connected": True,
            "chain_id": chain_id,
            "contract_address": self.contract_address,
            "rpc_url": self.web3.provider.endpoint_uri,
        }

    def anchor_root(self, root: bytes, leaf_count: int) -> dict[str, Any]:
        from requests.exceptions import RequestException
        from web3.exceptions import Web3Exception

        try:
            accounts = self.web3.eth.accounts
            if not accounts:
                raise ChainUnavailable("The local node has no unlocked account")
            transaction_hash = self.contract.functions.anchorRoot(
                root, leaf_count
            ).transact({"from": accounts[0]})
            receipt = self.web3.eth.wait_for_transaction_receipt(transaction_hash)
        except (RequestException, Web3Exception) as error:
            raise ChainUnavailable("The node could not anchor this batch") from error
        if receipt["status"] != 1:
            raise ChainUnavailable("The anchor transaction was reverted")
        return {
            "transaction_hash": transaction_hash.hex(),
            "block_number": receipt["blockNumber"],
            "contract_address": self.contract_address,
        }

    def is_anchored(self, root: bytes) -> bool:
        from requests.exceptions import RequestException
        from web3.exceptions import Web3Exception

        try:
            return bool(self.contract.functions.anchors(root).call()[3])
        except (RequestException, Web3Exception) as error:
            raise ChainUnavailable("The node could not check this batch root") from error

    def verify_proof(
        self, leaf: bytes, proof: Sequence[bytes], root: bytes
    ) -> bool:
        from requests.exceptions import RequestException
        from web3.exceptions import Web3Exception

        try:
            return bool(
                self.contract.functions.verifyProof(leaf, list(proof), root).call()
            )
        except (RequestException, Web3Exception) as error:
            raise ChainUnavailable("The node could not verify this Merkle proof") from error
