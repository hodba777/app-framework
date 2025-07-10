# app-framework: Cross-Chain Bridge Event Listener

This repository contains a Python-based simulation of a critical component in a cross-chain bridge system: the event listener and relayer. This script is designed to monitor a smart contract on a source blockchain for specific events (e.g., `TokensLocked`) and simulate the corresponding action (e.g., `unlockTokens`) on a destination blockchain.

It is architected to be robust, extensible, and illustrative of the patterns used in real-world decentralized applications.

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain (e.g., Ethereum) to another (e.g., Polygon). A common pattern for asset bridging works as follows:

1.  **Lock**: A user locks tokens in a bridge smart contract on the source chain. This action emits an event, such as `TokensLocked`.
2.  **Listen**: Off-chain services, called listeners or relayers, constantly monitor the source chain for these `TokensLocked` events.
3.  **Verify & Relay**: Upon detecting an event, the relayer verifies it and submits a corresponding transaction to a bridge contract on the destination chain.
4.  **Unlock/Mint**: The destination chain contract, upon successful verification of the relayer's transaction, unlocks or mints an equivalent amount of pegged tokens for the user.

This script simulates steps 2 and 3, forming the backbone of the bridge's off-chain infrastructure.

## Code Architecture

The script is designed with a clear separation of concerns, using several classes to manage different aspects of the process.

-   `BlockchainConnector`: 
    -   **Responsibility**: Manages the connection to a single blockchain via a Web3.py instance.
    -   **Features**: Handles RPC connections, provides helper methods to get contract instances and fetch the latest block number, and includes logic to handle PoA-chain middleware.

-   `EventListener`:
    -   **Responsibility**: The main orchestrator of the listening process.
    -   **Features**:
        -   Initializes connections to the source chain.
        -   Manages application state, specifically the `last_processed_block`, persisting it to a JSON file (`listener_state.json`) to ensure continuity across restarts.
        -   Contains the main execution loop that periodically polls the source chain for new blocks.
        -   Scans block ranges for target events (`TokensLocked`) and passes them to the `EventProcessor`.

-   `EventProcessor`:
    -   **Responsibility**: Encapsulates the logic for handling a detected event.
    -   **Features**:
        -   Initializes a connection to the destination chain.
        -   Takes a raw event as input and parses its arguments.
        -   **Simulates** the creation, signing, and sending of a transaction to the destination chain's bridge contract to unlock the tokens.
        -   Includes a helper method to fetch gas prices, demonstrating the use of an external library (`requests`) with a fallback mechanism.

-   **Configuration (`CONFIG`)**:
    -   A centralized dictionary holds all key parameters, such as RPC URLs, contract addresses, and private keys. In a production environment, this would be managed via environment variables (as hinted with `os.getenv`) and a more secure configuration service.

### Data Flow

```
+-----------------------+
| Main Execution Loop   |
| in EventListener.run()|
+-----------+-----------+
            |
            v
+-----------+-----------+
| Get Latest Block #    |
| on Source Chain       |
+-----------+-----------+
            |
            v
+-----------+-----------+
| Scan Block Range for  |
|   'TokensLocked'      |
+-----------+-----------+
            | (Event Found)
            v
+-----------+-----------+
|   EventProcessor      |
|  .process_event()     |
+-----------+-----------+
            |
            v
+-----------+-----------+
| Build & Sign 'unlock' |
| Tx for Dest. Chain    |
+-----------+-----------+
            |
            v
+-----------+-----------+
| [SIMULATE] Sending    |
| Transaction           |
+-----------------------+
```

## How it Works

1.  **Initialization**: On startup, the `EventListener` is instantiated. It loads its state from `listener_state.json` to determine which block it should start scanning from. If the file doesn't exist, it uses a default `start_block` from the configuration.

2.  **Connection**: The script establishes connections to both the source and destination chain RPC endpoints using the `BlockchainConnector` class.

3.  **Polling Loop**: The `EventListener` enters an infinite loop where it:
    a. Checks the latest block number on the source chain.
    b. Compares the latest block with its `last_processed_block` to determine the range of new blocks to scan.
    c. Fetches all `TokensLocked` events within this range using a contract event filter.

4.  **Event Processing**: For each event found:
    a. The `EventListener` passes the event data to the `EventProcessor`.
    b. The `EventProcessor` constructs an `unlockTokens` transaction for the destination chain.
    c. It fetches a gas price (simulating an API call).
    d. It signs the transaction with the relayer's private key.
    e. It logs the transaction details that *would* be sent to the blockchain, completing the simulation.

5.  **State Management**: After successfully scanning a batch of blocks, the `EventListener` updates `last_processed_block` and saves the new state to `listener_state.json`. This prevents reprocessing of events and allows the script to resume where it left off if it is stopped and restarted.

6.  **Error Handling**: The script includes `try...except` blocks to handle common issues like network connection errors, invalid block ranges (potential reorgs), and processing failures, ensuring the listener remains operational.

## Usage Example

1.  **Clone the repository**

    ```bash
    git clone <repository_url>
    cd app-framework
    ```

2.  **Install dependencies**

    Create a virtual environment and install the required packages.

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Set up configuration**

    The script is configured to use environment variables. Create a `.env` file in the root directory and populate it with your own data:

    ```.env
    # RPC URL for the source chain (e.g., an Infura or Alchemy URL for Sepolia)
    SEPOLIA_RPC_URL="https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID"

    # RPC URL for the destination chain (e.g., an Infura or Alchemy URL for Mumbai)
    MUMBAI_RPC_URL="https://polygon-mumbai.infura.io/v3/YOUR_INFURA_PROJECT_ID"

    # The private key for the relayer account on the destination chain
    # DANGER: Use a key from a test wallet with no real funds!
    RELAYER_PRIVATE_KEY="0xyour_private_key_here"
    ```

    You will also need to update the placeholder contract addresses in the `CONFIG` dictionary within `script.py` to point to your deployed bridge contracts.

4.  **Run the script**

    ```bash
    python script.py
    ```

5.  **Expected Output**

    You will see logs in your console and in the `bridge_listener.log` file. The output will show the script's progress as it connects to the chains, scans blocks, and processes events.

    ```
    2023-10-27 10:30:00,123 - INFO - [BlockchainConnector.Sepolia] - Successfully connected to Sepolia at https://rpc.sepolia.org
    2023-10-27 10:30:01,456 - INFO - [BlockchainConnector.Mumbai] - Successfully connected to Mumbai at https://rpc-mumbai.maticvigil.com
    2023-10-27 10:30:01,457 - INFO - [EventProcessor] - Relayer configured with address: 0xYourRelayerAddress
    2023-10-27 10:30:01,458 - INFO - [EventListener] - Loaded state: last processed block is 1000000.
    2023-10-27 10:30:01,458 - INFO - [EventListener] - Starting cross-chain event listener...
    2023-10-27 10:30:03,800 - INFO - [EventListener] - Scanning for 'TokensLocked' events from block 1000001 to 1000100...
    ...
    2023-10-27 10:30:05,900 - INFO - [EventListener] - Found 'TokensLocked' event in transaction 0x... at block 1000055.
    2023-10-27 10:30:05,901 - INFO - [EventProcessor] - Processing event with nonce 42: Unlock 100000000 tokens for 0x... on Mumbai.
    2023-10-27 10:30:06,500 - INFO - [EventProcessor] - [SIMULATION] Would send transaction to unlock tokens. Tx hash: 0x...
    ...
    2023-10-27 10:30:18,000 - INFO - [EventListener] - No new blocks to process. Current head: 1000100. Sleeping...
    ```
