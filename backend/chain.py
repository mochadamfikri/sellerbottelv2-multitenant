import httpx

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

EVM_CHAINS = {
    "POL": {
        "rpc": "https://polygon-rpc.com",
        "USDT": [("0xc2132d05d31c914a87c6611c10748aeb04b58e8f", 6)],
        "USDC": [("0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", 6), ("0x2791bca1f2de4661ed88a30c99a7a9449aa84174", 6)],
    },
    "BNB": {
        "rpc": "https://bsc-dataseed.binance.org",
        "USDT": [("0x55d398326f99059ff775485246999027b3197955", 18)],
        "USDC": [("0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", 18)],
    },
    "AVAX": {
        "rpc": "https://api.avax.network/ext/bc/C/rpc",
        "USDT": [("0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7", 6)],
        "USDC": [("0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e", 6), ("0xa7d7079b0fead91f3e65f86e8915cb59c1a4c664", 6)],
    },
}

SOL_MINTS = {
    "USDT": ["Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"],
    "USDC": ["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"],
}

SOL_RPC = "https://api.mainnet-beta.solana.com"


def looks_like_tx_hash(text: str, network: str) -> bool:
    t = text.strip()
    if network == "SOL":
        return 60 <= len(t) <= 90 and all(c.isalnum() for c in t)
    return t.startswith("0x") and len(t) == 66


async def verify_evm(network: str, coin: str, address: str, tx_hash: str, expected_sender: str | None = None):
    chain = EVM_CHAINS[network]
    contracts = {c: d for c, d in chain[coin]}
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.post(chain["rpc"], json={"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx_hash]})
            receipt = r.json().get("result")
    except Exception:
        return False, None, "Gagal terhubung ke jaringan blockchain"
    if not receipt:
        return False, None, "Transaksi tidak ditemukan di blockchain"
    if receipt.get("status") != "0x1":
        return False, None, "Transaksi gagal (reverted)"
    addr_suffix = address.lower().replace("0x", "").rjust(64, "0")
    sender_suffix = expected_sender.lower().replace("0x", "").rjust(64, "0") if expected_sender else None
    total = 0.0
    for log in receipt.get("logs", []):
        contract = log.get("address", "").lower()
        topics = log.get("topics", [])
        if contract in contracts and len(topics) >= 3 and topics[0].lower() == TRANSFER_TOPIC:
            if topics[2].lower().replace("0x", "") == addr_suffix:
                if sender_suffix and topics[1].lower().replace("0x", "") != sender_suffix:
                    continue
                total += int(log["data"], 16) / (10 ** contracts[contract])
    if total <= 0:
        return False, None, "Tidak ada transfer token yang cocok ke alamat deposit"
    return True, total, None


async def verify_sol(coin: str, address: str, tx_hash: str, expected_sender: str | None = None):
    mints = SOL_MINTS[coin]
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.post(SOL_RPC, json={
                "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                "params": [tx_hash.strip(), {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}],
            })
            result = r.json().get("result")
    except Exception:
        return False, None, "Gagal terhubung ke jaringan Solana"
    if not result:
        return False, None, "Transaksi tidak ditemukan di blockchain"
    meta = result.get("meta") or {}
    if meta.get("err") is not None:
        return False, None, "Transaksi gagal di Solana"
    pre = {}
    post = {}
    for b in meta.get("preTokenBalances", []):
        key = (b.get("owner"), b.get("mint"))
        pre[key] = pre.get(key, 0.0) + float(b["uiTokenAmount"].get("uiAmount") or 0)
    for b in meta.get("postTokenBalances", []):
        key = (b.get("owner"), b.get("mint"))
        post[key] = post.get(key, 0.0) + float(b["uiTokenAmount"].get("uiAmount") or 0)

    total = 0.0
    for key, after in post.items():
        owner, mint = key
        if owner == address and mint in mints:
            delta = after - pre.get(key, 0.0)
            if delta > 0:
                total += delta

    if expected_sender:
        outbound = 0.0
        for key, before in pre.items():
            owner, mint = key
            if owner == expected_sender and mint in mints:
                outbound += max(0.0, before - post.get(key, 0.0))
        if outbound <= 0:
            return False, None, "Wallet pengirim tidak cocok dengan transaksi"
    if total <= 0:
        return False, None, "Tidak ada transfer token yang cocok ke alamat deposit"
    return True, total, None


async def verify_tx(network: str, coin: str, address: str, tx_hash: str, expected_sender: str | None = None):
    if network == "SOL":
        return await verify_sol(coin, address, tx_hash, expected_sender)
    return await verify_evm(network, coin, address, tx_hash, expected_sender)
