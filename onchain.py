# onchain.py  [desk fix] 2026-11-01, owner-approved ("加链上备用数据源").
# Fallback fact source, used ONLY when rugcheck.xyz fails / times out / has no report.
# Free public data only, no keys: Solana JSON-RPC (public endpoints) + DexScreener.
# Scope is deliberately narrow: pump.fun tokens that graduated to their canonical PumpSwap pool, because
# that is the only case where the fallback can verify everything the rug filter needs from chain state:
#   mint / freeze authority, Token-2022 extensions, top holders (pool vaults removed), creator wallet
#   (pump.fun bonding-curve account), creator holdings, LP burned (LP mint supply vs pool lp_supply).
# What it can NOT verify: rugcheck's risk score, insider graph, creator rug history -> stricter caps in
# config.FALLBACK, tier A only, higher BUY confidence. Anything that can't be fetched -> exception (fail closed).
import base64, struct, time
import requests
from config import FACTS, FALLBACK

OFFICIAL = "https://api.mainnet-beta.solana.com"         # official public RPC: 429s getTokenLargestAccounts for everyone
SVS = "https://public.rpc.solanavibestation.com"         # free public RPC that serves it; ~4 calls/10s, so used sparingly
RPCS = [OFFICIAL, SVS]
FIRST = {"getTokenLargestAccounts": [SVS, OFFICIAL]}     # per-method endpoint order
DS = "https://api.dexscreener.com/tokens/v1/solana"
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"     # pump.fun bonding curve program
PUMP_AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"  # PumpSwap
WSOL = "So11111111111111111111111111111111111111112"
AMM_PROGRAMS = {PUMP, PUMP_AMM,                           # holder accounts owned by these programs are pools, not whales
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",       # Raydium AMM v4
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",       # Raydium CPMM
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",       # Raydium CLMM
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",        # Raydium LaunchLab
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",        # Meteora DLMM
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB",       # Meteora DAMM v1
    "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG",        # Meteora DAMM v2
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",        # Meteora DBC
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"}        # Orca Whirlpool
AMM_AUTHORITIES = {"5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",   # Raydium AMM v4 authority (system-owned PDA)
                   "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",   # Raydium CPMM authority
                   "WLHv2UAZm6z4KyaaELi5pjdbJh6RESMva1Rnn8pJVVh"}    # Raydium LaunchLab authority
# Token-2022 extensions that let someone other than the holder move, freeze, tax or block tokens
BAD_EXT = {"permanentDelegate", "transferHook", "nonTransferable", "pausableConfig", "confidentialTransferMint"}

TIMEOUT, TRIES, GAP = 10, 2, 0.25


class Unavailable(Exception):
    """a required fact could not be fetched -> caller SKIPs (fail closed)."""


def rpc(method, params):
    last = None
    for url in FIRST.get(method, RPCS):
        for i in range(TRIES):
            try:
                time.sleep(GAP)
                r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                  timeout=TIMEOUT)
                if r.status_code == 429:
                    last = f"{method} 429 {url.split('/')[2]}"; time.sleep(1 + i); continue
                r.raise_for_status()
                j = r.json()
                if "error" in j:
                    last = f"{method} {j['error'].get('code')} {url.split('/')[2]}"; break   # next endpoint
                return j["result"]
            except (requests.RequestException, ValueError) as e:
                last = f"{method} {type(e).__name__} {url.split('/')[2]}"; time.sleep(0.5 + i)
    raise Unavailable(f"rpc_unavailable:{last}")


def _pda(seeds, program):
    from solders.pubkey import Pubkey as P   # pip install --user solders (PDA derivation needs the ed25519 curve check)
    return str(P.find_program_address(seeds, P.from_string(program))[0])


def _b(addr):
    from solders.pubkey import Pubkey as P
    return bytes(P.from_string(addr))


def _pk(raw):
    from solders.pubkey import Pubkey as P
    return str(P.from_bytes(raw))


def _accounts(addrs, parsed=False):
    enc = {"encoding": "jsonParsed"} if parsed else {"encoding": "base64"}
    return rpc("getMultipleAccounts", [addrs, enc])["value"]


def report(mint: str) -> dict:
    """Same keys as rugcheck.report() plus fallback-only facts. Raises Unavailable when a required fact is missing."""
    # 1. mint account: authorities, supply, Token-2022 extensions
    acc = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]
    if not acc or (acc.get("data") or {}).get("parsed", {}).get("type") != "mint":
        raise Unavailable("mint_account_unreadable")
    info = acc["data"]["parsed"]["info"]
    supply = int(info["supply"])
    if supply <= 0:
        raise Unavailable("zero_supply")
    exts = {e.get("extension"): e.get("state") or {} for e in (info.get("extensions") or [])}
    bad_ext = sorted(k for k in exts if k in BAD_EXT)
    tf = exts.get("transferFeeConfig")
    if tf and any(int((tf.get(k) or {}).get("transferFeeBasisPoints") or 0) > 0 for k in ("newerTransferFee", "olderTransferFee")):
        bad_ext.append("transferFee")
    if (exts.get("defaultAccountState") or {}).get("accountState") == "frozen":
        bad_ext.append("defaultFrozen")
    meta = exts.get("tokenMetadata") or {}
    meta_mutable = bool(meta.get("updateAuthority")) if meta else None   # None = legacy SPL, not checked

    # 2. DexScreener pairs: every pool address for this mint is excluded from holders
    try:
        r = requests.get(f"{DS}/{mint}", timeout=TIMEOUT); r.raise_for_status()
        pairs = [p for p in (r.json() or []) if (p.get("baseToken") or {}).get("address") == mint
                 or (p.get("quoteToken") or {}).get("address") == mint]
    except (requests.RequestException, ValueError) as e:
        raise Unavailable(f"dexscreener_unavailable:{type(e).__name__}")
    pair_addrs = {p.get("pairAddress") for p in pairs}
    top_pair = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0) if pairs else None

    # 3. pump.fun origin: bonding-curve account (creator, complete flag) + the canonical PumpSwap pool, i.e. the one
    #    pump.fun's migration created: PDA ["pool", 0, pool-authority(mint), mint, quote]. Quote is usually WSOL, but
    #    pump.fun also launches against other quotes (PUMP, HYPE, xStocks...), so take the quote from the pumpswap pair.
    bc = _pda([b"bonding-curve", _b(mint)], PUMP)
    pool_auth = _pda([b"pool-authority", _b(mint)], PUMP)
    quotes = [WSOL] + [(p.get("quoteToken") or {}).get("address") for p in pairs
                       if p.get("dexId") == "pumpswap" and (p.get("baseToken") or {}).get("address") == mint]
    cands = list(dict.fromkeys(_pda([b"pool", struct.pack("<H", 0), _b(pool_auth), _b(mint), _b(q)], PUMP_AMM)
                               for q in quotes if q))
    got = _accounts([bc] + cands)
    bca, canon, pa = got[0], None, None
    for addr, acc_ in zip(cands, got[1:]):
        if acc_ and acc_["owner"] == PUMP_AMM:
            canon, pa = addr, acc_
            if addr in pair_addrs:
                break
    pumpfun = bool(bca and bca["owner"] == PUMP)
    creator, complete, lp_burned = None, None, None
    if pumpfun:
        d = base64.b64decode(bca["data"][0])
        complete = bool(d[48]) if len(d) > 48 else None
        creator = _pk(d[49:81]) if len(d) >= 81 else None
        if creator == "11111111111111111111111111111111":
            creator = None
    if pa:
        d = base64.b64decode(pa["data"][0])
        if len(d) >= 8 + 3 + 32 * 6 + 8 and _pk(d[11:43]) == pool_auth and _pk(d[43:75]) == mint:
            lp_mint = _pk(d[107:139])
            lp_total = struct.unpack_from("<Q", d, 11 + 32 * 6)[0]
            creator = creator or (_pk(d[11 + 32 * 6 + 8: 11 + 32 * 7 + 8]) if len(d) >= 11 + 32 * 7 + 8 else None)
            lp_live = int(rpc("getTokenSupply", [lp_mint])["value"]["amount"])
            lp_burned = round(100 * (1 - lp_live / lp_total), 2) if lp_total else None
        else:
            canon, pa = None, None

    # 4. top holders: largest token accounts -> owners -> drop pools / AMM vault authorities
    largest = rpc("getTokenLargestAccounts", [mint])["value"]
    if not largest:
        raise Unavailable("no_holders")
    tok = _accounts([a["address"] for a in largest], parsed=True)
    owners = [((t or {}).get("data") or {}).get("parsed", {}).get("info", {}).get("owner") for t in tok]
    uniq = sorted({o for o in owners if o})
    oacc = dict(zip(uniq, _accounts(uniq))) if uniq else {}
    pool_like = {bc, pool_auth, *cands} | pair_addrs | AMM_AUTHORITIES
    holders, excluded = [], 0.0
    for a, o in zip(largest, owners):
        pct = int(a["amount"]) / supply * 100
        prog = (oacc.get(o) or {}).get("owner")
        if o in pool_like or a["address"] in pair_addrs or prog in AMM_PROGRAMS:
            excluded += pct; continue
        holders.append({"address": a["address"], "owner": o, "pct": pct})
    top10 = holders[:10]
    # bundle proxy (no insider graph): several top wallets holding near-identical amounts = one buyer split up
    same = 0
    for h in top10:
        twins = sum(1 for g in top10 if g is not h and abs(g["pct"] - h["pct"]) <= FALLBACK["twin_tolerance"] * h["pct"])
        same = max(same, twins + 1 if twins else 0)

    # 5. creator holdings: every token account the creator owns for this mint
    dev_pct = None
    if creator:
        ta = rpc("getTokenAccountsByOwner", [creator, {"mint": mint}, {"encoding": "jsonParsed"}])["value"]
        amt = sum(int(t["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for t in ta)
        dev_pct = round(max(amt / supply * 100, sum(h["pct"] for h in holders if h["owner"] == creator)), 2)

    return {
        "source": "onchain_fallback",
        "mint": mint,
        "symbol": meta.get("symbol") or ((top_pair or {}).get("baseToken") or {}).get("symbol"),
        "rugged": False,                 # not knowable here; the pool stage + liquidity rules still apply
        "risk_score": None,              # rugcheck-only
        "danger": [], "warn": [],
        "mint_authority": info.get("mintAuthority"),
        "freeze_authority": info.get("freezeAuthority"),
        "lp_locked_pct": lp_burned,
        "top10_pct": round(sum(h["pct"] for h in top10), 2),
        "dev_pct": dev_pct,
        "insiders": None,                # rugcheck-only
        "holders": None,
        # fallback-only facts
        "creator": creator, "pumpfun": pumpfun, "graduated": complete,
        "canonical_pool": canon,
        "top_pair": (top_pair or {}).get("pairAddress"), "top_pair_dex": (top_pair or {}).get("dexId"),
        "max_holder_pct": round(holders[0]["pct"], 2) if holders else 0.0,
        "pool_excluded_pct": round(excluded, 2),
        "same_size_holders": same,
        "bad_extensions": bad_ext, "metadata_mutable": meta_mutable,
        "token_program": acc.get("owner"),
    }


def fact_kill(t: dict) -> str | None:
    """Fallback rug filter. Stricter than rugcheck.fact_kill; first failure wins, reason codes prefixed fb_."""
    F = FALLBACK
    if t["mint_authority"]:                                      return "mint_open"
    if t["freeze_authority"]:                                    return "freeze_open"
    if t["bad_extensions"]:                                      return "fb_t22_" + t["bad_extensions"][0]
    if t["metadata_mutable"]:                                    return "fb_metadata_mutable"
    if not t["pumpfun"]:                                         return "fb_not_pumpfun"       # can't verify creator / LP
    if not t["graduated"]:                                       return "bonding_curve"
    if not t["canonical_pool"]:                                  return "fb_no_canonical_pool"
    if t["top_pair"] != t["canonical_pool"]:                     return "fb_top_pool_not_canonical"   # biggest pool's LP unverified
    if t["lp_locked_pct"] is None or t["lp_locked_pct"] < FACTS["min_lp_locked_pct"]:
        return "lp_unlocked"
    cap = F["max_top10_pct"] if t["creator"] else F["max_top10_pct_no_creator"]
    if t["top10_pct"] > cap:                                     return "fb_top10_heavy"
    if t["max_holder_pct"] > F["max_single_holder_pct"]:         return "fb_single_holder"
    if t["creator"] and (t["dev_pct"] is None or t["dev_pct"] > FACTS["max_dev_pct"]):
        return "dev_holds"
    if t["same_size_holders"] >= F["max_same_size_holders"]:     return "fb_bundle_suspect"
    return None


if __name__ == "__main__":
    import json, sys
    t = report(sys.argv[1].strip())
    print(json.dumps({**t, "fact_kill": fact_kill(t)}, indent=1))
