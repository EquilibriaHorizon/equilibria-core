#pragma once

#include "mainnet.h"

namespace cryptonote::config::testnet {

// Private testnet: no hardcoded seeds; SNs connect via --seed-node flag
inline constexpr std::array<std::string_view, 0> seeds = {};

inline constexpr network_config config{
        .NETWORK_TYPE = network_type::TESTNET,
        .DEFAULT_CONFIG_SUBDIR = "testnet"sv,
        .HEIGHT_ESTIMATE_HEIGHT = 0,  // Reset for new chain
        .HEIGHT_ESTIMATE_TIMESTAMP = 0,  // Start from beginning
        .PUBLIC_ADDRESS_BASE58_PREFIX = 0x1c1eb4,
        .PUBLIC_INTEGRATED_ADDRESS_BASE58_PREFIX = 0x179eb4,
        .PUBLIC_SUBADDRESS_BASE58_PREFIX = 0x0f1eb4,
        .P2P_DEFAULT_PORT = 38156,
        .RPC_DEFAULT_PORT = 38157,
        .QNET_DEFAULT_PORT = 38159,
        .NETWORK_ID = {{
                0x58,  // X
                0x45,  // E
                0x51,  // Q
                0x4d,  // M (private testnet: XEQM-PVTTEST)
                0x50,  // P
                0x56,  // V
                0x54,  // T
                0x54,  // T
                0x45,  // E
                0x53,  // S
                0x54,  // T
                0x30,  // 0
                0x30,  // 0
                0x31,  // 1
                0x00,
                0x00,
        }},
        .P2P_SEED_NODES = seeds,
        .GENESIS_TX =
                "021e01ff00018080c9db97f4fb270278fe7eed60deb57ea863d65690c40abc5ff09505704f36ba94285a02b9e15f6942014c8f90cc270b3e4e154003ecf48f21b5762e57c52cc70df9c65502e4921cd97872000000000000000000000000000000000000000000000000000000000000000000"sv,
        .GENESIS_NONCE = 12345,
        .GOVERNANCE_REWARD_INTERVAL = 10min,
        .GOVERNANCE_WALLET_ADDRESS =
                {
                        "XEQTCMd5W5jX582CXuuQwzc6KY5mEHvXRNnLxoNQ6nA7Wq1ioBudM64Z835ygvWcrxTHyuuN5suvPiapbjbVAFeZ3NXFhKG2fx",  // HF20+ (index 0)
                        "XEQTCMd5W5jX582CXuuQwzc6KY5mEHvXRNnLxoNQ6nA7Wq1ioBudM64Z835ygvWcrxTHyuuN5suvPiapbjbVAFeZ3NXFhKG2fx",  // HF10-19 (index 1)
                },
        .UPTIME_PROOF_TOLERANCE = mainnet::config.UPTIME_PROOF_TOLERANCE,
        .UPTIME_PROOF_STARTUP_DELAY = 5s,
        .UPTIME_PROOF_CHECK_INTERVAL = 5s,
        // Testnet uptime proofs are 6x faster than mainnet (devnet config also uses these)
        .UPTIME_PROOF_FREQUENCY = 30s,
        .UPTIME_PROOF_VALIDITY = 120s,
        .HAVE_STORAGE_SERVER = false,
        .HAVE_SESSION_ROUTER = false,
        .HAVE_LOKINET = false,
        .TARGET_BLOCK_TIME = 5s,
        .PULSE_STAGE_TIMEOUT = mainnet::config.PULSE_STAGE_TIMEOUT,
        .PULSE_ROUND_TIMEOUT = mainnet::config.PULSE_ROUND_TIMEOUT,
        .PULSE_MAX_START_ADJUSTMENT = mainnet::config.PULSE_MAX_START_ADJUSTMENT,
        .PULSE_MINER_FALLBACK_ROUNDS = 2,  // 2 * 30s = 60s, gives R1 a window after R0 fails
        .PULSE_MIN_SERVICE_NODES = 12,  // == pulse quorum size
        .BATCHING_INTERVAL = 20,
        .MIN_BATCH_PAYMENT_AMOUNT = mainnet::config.MIN_BATCH_PAYMENT_AMOUNT,
        .BATCHING_INTERVAL_V2 = 5,
        .MIN_BATCH_PAYMENT_AMOUNT_V2 = mainnet::config.MIN_BATCH_PAYMENT_AMOUNT,
        .LIMIT_BATCH_OUTPUTS = mainnet::config.LIMIT_BATCH_OUTPUTS,
        .SERVICE_NODE_PAYABLE_AFTER_BLOCKS = 4,
        .DEREGISTRATION_LOCK_DURATION = 30s,
        .DEREGISTRATION_LOCK_DURATION_V2 = 30s,
        .UNLOCK_DURATION = 30s,
        .HARDFORK_DEREGISTRATION_GRACE_PERIOD =
                mainnet::config.HARDFORK_DEREGISTRATION_GRACE_PERIOD,
        .HISTORY_ARCHIVE_INTERVAL = mainnet::config.HISTORY_ARCHIVE_INTERVAL,
        .HISTORY_ARCHIVE_KEEP_WINDOW = mainnet::config.HISTORY_ARCHIVE_KEEP_WINDOW,
        .HISTORY_RECENT_KEEP_WINDOW = mainnet::config.HISTORY_RECENT_KEEP_WINDOW,
        // Much shorter than mainnet so that you can test this more easily.
        .ETH_EXIT_BUFFER = 1h / mainnet::config.TARGET_BLOCK_TIME,
        .ETHEREUM_CHAIN_ID = 421614,  // Arbitrum Sepolia
        .ETHEREUM_REWARDS_CONTRACT = "0x5FC8d32690cc91D4c39d9d3abcBD16989F875707",// "0x0B5C58A27A41D5fE3FF83d74060d761D7dDDc1D2",
        .ETHEREUM_POOL_CONTRACT = "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0",// "0x8D69Bb9D7b03993234bfd221aCB391Db597a920a",
        // Sepolia arbitrum sometimes slows down below the typical 250ms seen on mainnet, so for
        // testnet/devnet we shorten this to a quarter compared to mainnet:
        .L2_REWARD_POOL_UPDATE_BLOCKS = mainnet::config.L2_REWARD_POOL_UPDATE_BLOCKS / 4,
        .L2_TRACKER_SAFE_BLOCKS = mainnet::config.L2_TRACKER_SAFE_BLOCKS,
        // arb sepolia blocks are (sometimes) slower than mainnet, so reduce this a bit so that
        // we're probably still somewhere in the 1-2 hour range:
        .L2_NODE_LIST_PURGE_BLOCKS = mainnet::config.L2_NODE_LIST_PURGE_BLOCKS / 2,
        .L2_NODE_LIST_PURGE_MIN_OXEN_AGE = mainnet::config.L2_NODE_LIST_PURGE_MIN_OXEN_AGE,
        .DEFAULT_STAKING_URL = ""sv,
};
}  // namespace cryptonote::config::testnet
