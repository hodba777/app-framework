import os
import time
import logging
import json
from typing import Dict, Any, Optional, List

from web3 import Web3
from web3.contract import Contract
from web3.middleware import geth_poa_middleware
from web3.exceptions import BlockNotFound
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration --- #
# In a real-world application, this would be loaded from a more secure and flexible configuration system.
CONFIG = {
    "source_chain": {
        "name": "Sepolia",
        "rpc_url": os.getenv("SEPOLIA_RPC_URL", "https://rpc.sepolia.org"),
        "bridge_contract_address": "0x1234567890123456789012345678901234567890", # Placeholder address
        "start_block": 1000000 # Block to start scanning from if no state file is found
    },
    "destination_chain": {
        "name": "Mumbai",
        "rpc_url": os.getenv("MUMBAI_RPC_URL", "https://rpc-mumbai.maticvigil.com"),
        "bridge_contract_address": "0x0987654321098765432109876543210987654321", # Placeholder address
        "relayer_private_key": os.getenv("RELAYER_PRIVATE_KEY", "0x" + "a"*64) # DANGER: For simulation only. NEVER hardcode private keys.
    },
    "listener_settings": {
        "poll_interval_seconds": 15,
        "block_processing_batch_size": 100, # Process up to 100 blocks at a time
        "state_file": "listener_state.json"
    },
    "api_keys": {
        "gas_oracle_api": os.getenv("GAS_ORACLE_API_KEY", "your_api_key_here")
    }
}

# --- Contract ABI (Simplified) --- #
# This is a simplified ABI for demonstration purposes.
BRIDGE_CONTRACT_ABI = json.loads('''
[
    {
        "anonymous": false,
        "inputs": [
            {"indexed": true, "name": "from", "type": "address"},
            {"indexed": true, "name": "toChainId", "type": "uint256"},
            {"indexed": false, "name": "amount", "type": "uint256"},
            {"indexed": false, "name": "nonce", "type": "uint256"}
        ],
        "name": "TokensLocked",
        "type": "event"
    },
    {
        "inputs": [
            {"name": "recipient", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "sourceNonce", "type": "uint256"}
        ],
        "name": "unlockTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]
''')

# --- Logging Configuration --- #
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bridge_listener.log')
    ]
)


class BlockchainConnector:
    """Manages the connection to a single blockchain via Web3.py."""

    def __init__(self, name: str, rpc_url: str):
        """
        Initializes the connector.

        Args:
            name (str): The name of the chain (for logging purposes).
            rpc_url (str): The RPC endpoint URL for the blockchain node.
        """
        self.name = name
        self.rpc_url = rpc_url
        self.web3: Optional[Web3] = None
        self.logger = logging.getLogger(f"BlockchainConnector.{self.name}")
        self.connect()

    def connect(self):
        """Establishes a connection to the blockchain node."""
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            # Middleware for PoA chains like Polygon Mumbai or Goerli
            self.web3.middleware_onion.inject(geth_poa_middleware, layer=0)
            
            if self.web3.is_connected():
                self.logger.info(f"Successfully connected to {self.name} at {self.rpc_url}")
            else:
                raise ConnectionError(f"Failed to connect to {self.name}")
        except Exception as e:
            self.logger.error(f"Connection error for {self.name}: {e}")
            self.web3 = None

    def is_connected(self) -> bool:
        """Checks if the Web3 instance is connected."""
        return self.web3 is not None and self.web3.is_connected()

    def get_contract(self, address: str, abi: List[Dict[str, Any]]) -> Optional[Contract]:
        """
        Returns a Web3 contract instance.

        Args:
            address (str): The contract's address.
            abi (List[Dict[str, Any]]): The contract's ABI.

        Returns:
            Optional[Contract]: A Web3 contract instance or None if not connected.
        """
        if not self.is_connected() or not self.web3:
            self.logger.warning("Cannot get contract, not connected.")
            return None
        return self.web3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)

    def get_latest_block_number(self) -> Optional[int]:
        """
        Retrieves the latest block number from the chain.

        Returns:
            Optional[int]: The latest block number or None on failure.
        """
        if not self.is_connected() or not self.web3:
            self.logger.warning("Cannot get latest block, not connected.")
            return None
        try:
            return self.web3.eth.block_number
        except Exception as e:
            self.logger.error(f"Failed to get latest block number: {e}")
            return None

class EventListener:
    """The core component that listens for events on the source chain and triggers processing."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the EventListener.

        Args:
            config (Dict[str, Any]): The global configuration dictionary.
        """
        self.config = config
        self.logger = logging.getLogger("EventListener")
        self.state_file = config['listener_settings']['state_file']

        # Initialize source chain components
        source_chain_config = config['source_chain']
        self.source_connector = BlockchainConnector(source_chain_config['name'], source_chain_config['rpc_url'])
        self.source_bridge_contract = self.source_connector.get_contract(
            source_chain_config['bridge_contract_address'],
            BRIDGE_CONTRACT_ABI
        )

        # Initialize destination chain components for the processor
        self.event_processor = EventProcessor(config)

        self.last_processed_block = self._load_state()

    def _load_state(self) -> int:
        """Loads the last processed block number from the state file."""
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                last_block = int(state.get('last_processed_block', self.config['source_chain']['start_block']))
                self.logger.info(f"Loaded state: last processed block is {last_block}.")
                return last_block
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.warning(f"State file not found or invalid. Starting from default start block: {self.config['source_chain']['start_block']}")
            return self.config['source_chain']['start_block']

    def _save_state(self):
        """Saves the last processed block number to the state file."""
        with open(self.state_file, 'w') as f:
            json.dump({'last_processed_block': self.last_processed_block}, f)
            self.logger.debug(f"Saved state: last processed block is {self.last_processed_block}.")

    def run(self):
        """The main loop of the event listener."""
        self.logger.info("Starting cross-chain event listener...")
        while True:
            try:
                if not self.source_connector.is_connected():
                    self.logger.warning("Source chain disconnected. Attempting to reconnect...")
                    self.source_connector.connect()
                    time.sleep(self.config['listener_settings']['poll_interval_seconds'])
                    continue

                latest_block = self.source_connector.get_latest_block_number()
                if latest_block is None:
                    time.sleep(self.config['listener_settings']['poll_interval_seconds'])
                    continue

                # Determine the range of blocks to scan
                from_block = self.last_processed_block + 1
                to_block = min(latest_block, from_block + self.config['listener_settings']['block_processing_batch_size'] - 1)

                if from_block > latest_block:
                    self.logger.info(f"No new blocks to process. Current head: {latest_block}. Sleeping...")
                else:
                    self.logger.info(f"Scanning for 'TokensLocked' events from block {from_block} to {to_block}...")
                    self._process_block_range(from_block, to_block)
                    self.last_processed_block = to_block
                    self._save_state()

                time.sleep(self.config['listener_settings']['poll_interval_seconds'])

            except KeyboardInterrupt:
                self.logger.info("Shutdown signal received. Exiting...")
                break
            except Exception as e:
                self.logger.error(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
                time.sleep(self.config['listener_settings']['poll_interval_seconds'] * 2) # Longer sleep on error

    def _process_block_range(self, from_block: int, to_block: int):
        """Scans a range of blocks for relevant events and processes them."""
        if not self.source_bridge_contract:
            self.logger.error("Source bridge contract not initialized. Skipping block processing.")
            return
        try:
            event_filter = self.source_bridge_contract.events.TokensLocked.create_filter(
                fromBlock=from_block,
                toBlock=to_block
            )
            events = event_filter.get_all_entries()

            if not events:
                self.logger.debug(f"No 'TokensLocked' events found in blocks {from_block}-{to_block}.")
                return

            for event in events:
                self.logger.info(f"Found 'TokensLocked' event in transaction {event['transactionHash'].hex()} at block {event['blockNumber']}.")
                self.event_processor.process_event(event)

        except BlockNotFound:
            self.logger.warning(f"Block range [{from_block}-{to_block}] not found. This might be due to a chain reorg. Will retry.")
            # In a reorg, we might need to roll back self.last_processed_block. 
            # For this simulation, we'll just pause and retry.
            time.sleep(self.config['listener_settings']['poll_interval_seconds'])
        except Exception as e:
            self.logger.error(f"Error fetching events for blocks {from_block}-{to_block}: {e}")


class EventProcessor:
    """Handles the logic for processing a detected event, e.g., by sending a transaction to the destination chain."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger("EventProcessor")

        dest_chain_config = config['destination_chain']
        self.dest_connector = BlockchainConnector(dest_chain_config['name'], dest_chain_config['rpc_url'])
        self.dest_bridge_contract = self.dest_connector.get_contract(
            dest_chain_config['bridge_contract_address'],
            BRIDGE_CONTRACT_ABI
        )
        self.relayer_account = self.dest_connector.web3.eth.account.from_key(dest_chain_config['relayer_private_key']) if self.dest_connector.web3 else None
        self.logger.info(f"Relayer configured with address: {self.relayer_account.address if self.relayer_account else 'N/A'}")

    def process_event(self, event: Dict[str, Any]):
        """Processes a single 'TokensLocked' event by simulating an 'unlockTokens' transaction."""
        if not self.dest_bridge_contract or not self.relayer_account or not self.dest_connector.web3:
            self.logger.error("Destination chain components are not initialized. Cannot process event.")
            return
        
        try:
            event_args = event['args']
            recipient = event_args['from'] # In this simple model, the locker is the recipient on the other side
            amount = event_args['amount']
            nonce = event_args['nonce']

            self.logger.info(f"Processing event with nonce {nonce}: Unlock {amount} tokens for {recipient} on {self.dest_connector.name}.")

            # --- Transaction Simulation --- #
            # In a real system, you would build, sign, and send the transaction.
            # Here, we simulate this process.

            w3 = self.dest_connector.web3
            
            # 1. Build the transaction
            tx_data = self.dest_bridge_contract.functions.unlockTokens(
                recipient,
                amount,
                nonce
            ).build_transaction({
                'from': self.relayer_account.address,
                'nonce': w3.eth.get_transaction_count(self.relayer_account.address),
                'gas': 200000, # A fixed gas limit for simulation
                'gasPrice': self._get_gas_price()
            })

            # 2. Sign the transaction
            signed_tx = self.relayer_account.sign_transaction(tx_data)

            # 3. (SIMULATED) Send the transaction
            self.logger.info(f"[SIMULATION] Would send transaction to unlock tokens. Tx hash: {signed_tx.hash.hex()}")
            # In a real implementation:
            # tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            # self.logger.info(f"Transaction sent successfully! Receipt: {receipt}")

        except Exception as e:
            self.logger.error(f"Failed to process event {event['transactionHash'].hex()}: {e}", exc_info=True)

    def _get_gas_price(self) -> int:
        """Fetches a suitable gas price. Falls back from external API to node's suggestion."""
        # Example of using the 'requests' library for an external dependency
        try:
            # This is a placeholder for a real gas oracle API
            response = requests.get('https://api.gasoracle.io/v1/price', params={'apiKey': self.config['api_keys']['gas_oracle_api']})
            response.raise_for_status()
            gas_price_gwei = response.json()['fast']
            self.logger.debug(f"Fetched gas price from API: {gas_price_gwei} Gwei")
            return Web3.to_wei(gas_price_gwei, 'gwei')
        except Exception as e:
            self.logger.warning(f"Could not fetch gas price from external API ({e}). Falling back to node's suggestion.")
            if self.dest_connector.web3:
                return self.dest_connector.web3.eth.gas_price
            return Web3.to_wei(20, 'gwei') # Hardcoded fallback

if __name__ == '__main__':
    listener = EventListener(CONFIG)
    listener.run()


