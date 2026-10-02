"""Live / dry enrich for full FEATURE_SETS['+q5b'] ≤T0 (Q5a microstructure + Q5b creator/age).

Cost (Bitquery FREE — treat as expensive)
-----------------------------------------
Per batch of *new* mints when enrich_q5 enabled:

| Call | Query | Purpose |
|------|-------|---------|
| 1 | ``DEXTradeByTokens`` buys+sells (desc, limit) | Q5a + ``buy_vol_usd_60s`` |
| 2 | ``Instructions`` create/create_v2 for mints | age_s, has_creator, name/symbol |
| 3 | ``Instructions`` create by creator (30d) | creator_prior_mints_* |

Poll MC is separate (+1). Default live session tip: ``--max-calls 8`` for 1 cycle
with full enrich (poll+3). Dry-run: ``data/samples/q5_live_fixture.json`` (0 calls).

Dune: **not used live** (batch lag hours–days). Offline WF only.

Anti look-ahead: discard trades/creates with ts > mint T0; priors use create_ts < this create.
Missing pack → features incomplete → scorer skips (no substitutes).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from features.post_q5_sets import FEATURE_SETS, Q5A_COLS, Q5B_COLS
from paper_live.buy_vol import WINDOW_S, _parse_ts, _usd_from_trade
from paper_live.config import SAMPLE_Q5_FIXTURE
from paper_live.q5a_agg import TradeRow, aggregate_q5a_for_mint
from paper_live.q5b_agg import (
    CreateRow,
    prefer_sighting_meta_name_symbol,
    fill_meta_from_dune_store_exact,
    q5b_from_create,
)

WSOL = "So11111111111111111111111111111111111111112"

# Buys + sells for Q5a; also drives buy_vol_usd_60s client-side.
QUERY_TRADES_Q5A = """
query Q5aTradesPreT0(
  $mints: [String!]
  $hoursAgo: Int!
  $limit: Int!
  $programs: [String!]
) {
  Solana {
    DEXTradeByTokens(
      limit: { count: $limit }
      orderBy: { descending: Block_Time }
      where: {
        Trade: {
          Currency: { MintAddress: { in: $mints } }
          Dex: { ProgramAddress: { in: $programs } }
          Side: { Type: { in: [buy, sell] } }
        }
        Transaction: { Result: { Success: true } }
        Block: { Time: { since_relative: { hours_ago: $hoursAgo } } }
      }
    ) {
      Block { Time }
      Transaction { Signer }
      Trade {
        Account { Address }
        Currency { MintAddress }
        Amount
        AmountInUSD
        Side {
          Type
          Amount
          AmountInUSD
          Account { Address }
          Currency { MintAddress Symbol }
        }
        Dex { ProgramAddress ProtocolName }
      }
    }
  }
}
"""

# Pump create / create_v2 for sample mints (mint in Accounts).
QUERY_CREATES_FOR_MINTS = """
query Q5bCreatesForMints(
  $mints: [String!]
  $hoursAgo: Int!
  $limit: Int!
  $program: String!
) {
  Solana {
    Instructions(
      limit: { count: $limit }
      orderBy: { descending: Block_Time }
      where: {
        Transaction: { Result: { Success: true } }
        Instruction: {
          Program: {
            Address: { is: $program }
            Method: { in: ["create", "create_v2"] }
          }
          Accounts: { includes: { Address: { in: $mints } } }
        }
        Block: { Time: { since_relative: { hours_ago: $hoursAgo } } }
      }
    ) {
      Block { Time }
      Transaction { Signer }
      Instruction {
        Program {
          Method
          Arguments {
            Name
            Value {
              ... on Solana_ABI_String_Value_Arg { string }
              ... on Solana_ABI_Address_Value_Arg { address }
            }
          }
        }
        Accounts { Address }
      }
    }
  }
}
"""

# Prior creates by creator signers (30d window).
QUERY_CREATES_BY_CREATORS = """
query Q5bCreatesByCreators(
  $creators: [String!]
  $hoursAgo: Int!
  $limit: Int!
  $program: String!
) {
  Solana {
    Instructions(
      limit: { count: $limit }
      orderBy: { descending: Block_Time }
      where: {
        Transaction: { Result: { Success: true }, Signer: { in: $creators } }
        Instruction: {
          Program: {
            Address: { is: $program }
            Method: { in: ["create", "create_v2"] }
          }
        }
        Block: { Time: { since_relative: { hours_ago: $hoursAgo } } }
      }
    ) {
      Block { Time }
      Transaction { Signer }
      Instruction {
        Program {
          Method
          Arguments {
            Name
            Value {
              ... on Solana_ABI_String_Value_Arg { string }
              ... on Solana_ABI_Address_Value_Arg { address }
            }
          }
        }
        Accounts { Address }
      }
    }
  }
}
"""


@dataclass
class Q5EnrichResult:
    mint: str
    features: dict[str, Any] = field(default_factory=dict)
    buy_vol_usd_60s: float | None = None
    buy_count_60s: int | None = None
    q5a_ok: bool = False
    q5b_ok: bool = False
    source: str = "unavailable"
    detail: str = ""

    @property
    def complete_q5b(self) -> bool:
        """True when buy60 + Q5a + Q5b packs present (all_in_window may stay null)."""
        if not (self.q5a_ok and self.q5b_ok and self.buy_vol_usd_60s is not None):
            return False
        for c in FEATURE_SETS["+q5b"]:
            if c == "creator_prior_mints_all_in_window":
                continue
            if self.features.get(c) is None:
                # share/pct null OK when no buy volume (train parity)
                if c.endswith("_share") or c.endswith("_pct_proxy") or c in (
                    "max_buy_share",
                    "max_buy_sol",
                    "max_buy_usd",
                    "sniper_vol_share_5s",
                    "first5_buy_vol_share",
                ):
                    if float(self.features.get("buy_count_total") or 0) == 0:
                        continue
                return False
        return True


def load_q5_fixture(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or SAMPLE_Q5_FIXTURE
    data = json.loads(p.read_text())
    return dict(data.get("by_mint") or {})


def enrich_q5_from_fixture(
    mints: list[str],
    *,
    path: Path | None = None,
) -> dict[str, Q5EnrichResult]:
    by = load_q5_fixture(path)
    out: dict[str, Q5EnrichResult] = {}
    for mint in mints:
        row = by.get(mint)
        if not row:
            out[mint] = Q5EnrichResult(mint=mint, detail="mint absent from q5 fixture")
            continue
        feats = {c: row.get(c) for c in FEATURE_SETS["+q5b"]}
        # carry join meta if present
        for k in ("creator_pubkey", "create_ts", "buy_count_60s"):
            if k in row:
                feats[k] = row[k]
        bv = row.get("buy_vol_usd_60s")
        out[mint] = Q5EnrichResult(
            mint=mint,
            features=feats,
            buy_vol_usd_60s=float(bv) if bv is not None else None,
            buy_count_60s=int(row["buy_count_60s"]) if row.get("buy_count_60s") is not None else None,
            q5a_ok=all(row.get(c) is not None or c.endswith("_share") or c.endswith("_pct_proxy") or c in ("max_buy_share", "max_buy_sol", "max_buy_usd", "sniper_vol_share_5s", "first5_buy_vol_share") for c in Q5A_COLS),
            q5b_ok=all(
                row.get(c) is not None
                for c in Q5B_COLS
                if c != "creator_prior_mints_all_in_window"
            ),
            source="dry_run.q5_fixture",
            detail="fixture",
        )
    return out


def _project_from_program(
    prog: str | None,
    pump: str,
    pumpswap: str,
    *,
    protocol_name: str | None = None,
    default_pump: bool = True,
) -> str:
    """Map Dex program → Dune ``project`` label (pumpdotfun|pumpswap|other).

    Bitquery often returns null ``Dex.ProgramAddress`` even when the query filtered
    by pump programs — default to pumpdotfun so ``net_sol_curve`` is not zeroed.
    """
    if prog == pump:
        return "pumpdotfun"
    if prog == pumpswap:
        return "pumpswap"
    pn = (protocol_name or "").lower().replace(" ", "")
    if pn:
        if "pumpswap" in pn or pn == "pumpamm":
            return "pumpswap"
        if "pump" in pn:
            return "pumpdotfun"
    if not prog and default_pump:
        return "pumpdotfun"
    if not prog:
        return "unknown"
    return "other"


def _trader_id(tr: dict[str, Any]) -> str:
    trade = tr.get("Trade") or {}
    side = trade.get("Side") or {}
    for obj in (side.get("Account"), trade.get("Account")):
        if isinstance(obj, dict) and obj.get("Address"):
            return str(obj["Address"])
    signer = (tr.get("Transaction") or {}).get("Signer")
    if signer:
        return str(signer)
    return "unknown"


def parse_bitquery_trades(
    raw: list[dict[str, Any]],
    *,
    pump: str,
    pumpswap: str,
    sol_usd: float | None = None,
    min_amount_usd: float = 1.0,
) -> list[TradeRow]:
    """Parse Bitquery DEXTradeByTokens → TradeRow with Dune-parity USD/SOL/project.

    Bitquery quirks vs Dune ``dex_solana.trades`` (see cycle0 Q5a SQL):
    - ``Side.Amount`` (SOL) is often null → derive ``sol_amt = amount_usd / sol_usd``.
    - ``AmountInUSD`` sometimes null when ``Side.Amount`` present → derive USD.
    - ``Dex.ProgramAddress`` often null despite program filter → default pumpdotfun.
    - Dune filters ``amount_usd >= 1``; we apply the same after derivation.
    """
    from paper_live.config import DEFAULT_SOL_USD_REF

    sol_px = float(sol_usd) if sol_usd and sol_usd > 0 else float(DEFAULT_SOL_USD_REF)
    rows: list[TradeRow] = []
    for tr in raw:
        trade = tr.get("Trade") or {}
        mint = (trade.get("Currency") or {}).get("MintAddress")
        if not mint:
            continue
        ts_raw = (tr.get("Block") or {}).get("Time")
        if not ts_raw:
            continue
        side_obj = trade.get("Side") or {}
        side = (side_obj.get("Type") or "").lower()
        if side not in ("buy", "sell"):
            continue

        quote_mint = (side_obj.get("Currency") or {}).get("MintAddress")
        # Quote is SOL when WSOL, missing, or empty (Bitquery often omits Side.Currency)
        quote_is_sol = (not quote_mint) or quote_mint == WSOL

        sol_amt = 0.0
        if quote_is_sol:
            try:
                raw_amt = side_obj.get("Amount")
                if raw_amt is not None and str(raw_amt) != "":
                    sol_amt = float(raw_amt)
            except (TypeError, ValueError):
                sol_amt = 0.0
            # Lamports mistaken as UI? (>1e6 SOL impossible for a single pump buy)
            if sol_amt > 1_000_000:
                sol_amt = sol_amt / 1e9

        usd = _usd_from_trade(tr)
        # Derive missing leg for SOL-quoted pump trades (Dune always has both)
        if quote_is_sol:
            if (usd is None or usd <= 0) and sol_amt > 0:
                usd = sol_amt * sol_px
            if sol_amt <= 0 and usd is not None and usd > 0:
                sol_amt = float(usd) / sol_px
        if usd is None:
            continue
        try:
            usd_f = float(usd)
        except (TypeError, ValueError):
            continue
        if not (usd_f >= 0):
            continue
        # Dune parity: amount_usd >= 1
        if min_amount_usd > 0 and usd_f < min_amount_usd:
            continue

        try:
            tok_amt = float(trade.get("Amount") or 0.0)
        except (TypeError, ValueError):
            tok_amt = 0.0
        dex = trade.get("Dex") or {}
        prog = dex.get("ProgramAddress")
        protocol = dex.get("ProtocolName") or dex.get("ProtocolFamily")
        rows.append(
            TradeRow(
                mint=str(mint),
                ts=_parse_ts(ts_raw),
                side=side,
                amount_usd=usd_f,
                trader_id=_trader_id(tr),
                tok_amt=tok_amt,
                sol_amt=float(sol_amt) if sol_amt > 0 else 0.0,
                project=_project_from_program(prog, pump, pumpswap, protocol_name=protocol),
            )
        )
    return rows


def _arg_map(instr: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in instr.get("Arguments") or []:
        name = (a.get("Name") or "").lower()
        val = a.get("Value") or {}
        if "string" in val and val["string"] is not None:
            out[name] = val["string"]
        elif "address" in val and val["address"] is not None:
            out[name] = val["address"]
    return out


def parse_bitquery_creates(raw: list[dict[str, Any]], *, mint_hint: set[str] | None = None) -> list[CreateRow]:
    """Parse Pump create instructions → CreateRow. Mint from args or Accounts."""
    out: list[CreateRow] = []
    for ix in raw:
        instr = ix.get("Instruction") or {}
        ts_raw = (ix.get("Block") or {}).get("Time")
        if not ts_raw:
            continue
        # Bitquery: Arguments live under Instruction.Program (not Instruction)
        prog = instr.get("Program") or {}
        args = _arg_map({"Arguments": prog.get("Arguments") or instr.get("Arguments")})
        accounts = [a.get("Address") for a in (instr.get("Accounts") or []) if a.get("Address")]
        mint = args.get("mint") or args.get("token") 
        if not mint and mint_hint:
            for a in accounts:
                if a in mint_hint:
                    mint = a
                    break
        if not mint and accounts:
            # pump create: mint often accounts[0] or ends with 'pump'
            for a in accounts:
                if str(a).endswith("pump"):
                    mint = a
                    break
            if not mint:
                mint = accounts[0]
        if not mint:
            continue
        if mint_hint is not None and mint not in mint_hint and not any(
            a in mint_hint for a in accounts
        ):
            # still accept if mint_hint None; if set, require membership
            if mint not in mint_hint:
                # try accounts intersection
                hit = [a for a in accounts if a in mint_hint]
                if hit:
                    mint = hit[0]
                else:
                    continue
        creator = (ix.get("Transaction") or {}).get("Signer") or args.get("creator") or args.get("user")
        name = args.get("name")
        symbol = args.get("symbol")
        out.append(
            CreateRow(
                mint=str(mint),
                creator_pubkey=str(creator) if creator else None,
                create_ts=_parse_ts(ts_raw),
                token_name=str(name) if name else None,
                token_symbol=str(symbol) if symbol else None,
            )
        )
    return out


def _hours_covering(mint_t0: dict[str, datetime], *, extra_s: int = WINDOW_S, pad_h: int = 1) -> int:
    now = datetime.now(timezone.utc)
    oldest = min(mint_t0.values()) - timedelta(seconds=extra_s)
    span_h = (now - oldest).total_seconds() / 3600.0
    return max(1, int(math.ceil(span_h)) + pad_h)


def fetch_q5a_and_buy60(
    mint_t0: dict[str, datetime],
    *,
    client: Any,
    trade_limit: int = 2000,
    hours_ago: int | None = None,
) -> tuple[dict[str, dict[str, float | None]], dict[str, tuple[float, int]]]:
    """1 Bitquery call → Q5a feats + buy_vol_usd_60s per mint."""
    from ingestion.pump_constants import PUMP_PROGRAM_ID, PUMPSWAP_PROGRAM_ID

    if not mint_t0:
        return {}, {}
    # Full create→T0 history (Dune uses up to 7d). Never use poll-window (2h) alone.
    from paper_live.config import DEFAULT_Q5A_HOURS_AGO

    cover = _hours_covering(mint_t0, extra_s=7 * 86400, pad_h=2)
    if hours_ago is None:
        ha = max(DEFAULT_Q5A_HOURS_AGO, cover)
    else:
        ha = max(int(hours_ago), DEFAULT_Q5A_HOURS_AGO, min(cover, 24 * 7))
    ha = min(ha, 24 * 40)  # Bitquery practical cap
    body = client.graphql(
        QUERY_TRADES_Q5A,
        {
            "mints": list(mint_t0.keys()),
            "hoursAgo": ha,
            "limit": trade_limit,
            "programs": [PUMP_PROGRAM_ID, PUMPSWAP_PROGRAM_ID],
        },
    )
    raw = (((body.get("data") or {}).get("Solana") or {}).get("DEXTradeByTokens")) or []
    parsed = parse_bitquery_trades(raw, pump=PUMP_PROGRAM_ID, pumpswap=PUMPSWAP_PROGRAM_ID)
    by_mint: dict[str, list[TradeRow]] = {m: [] for m in mint_t0}
    for tr in parsed:
        if tr.mint in by_mint:
            by_mint[tr.mint].append(tr)

    q5a: dict[str, dict[str, float | None]] = {}
    buy60: dict[str, tuple[float, int]] = {}
    for mint, t0 in mint_t0.items():
        t0a = _parse_ts(t0)
        rows = by_mint.get(mint, [])
        # filter ≤ T0
        rows_le = [r for r in rows if r.ts <= t0a]
        q5a[mint] = aggregate_q5a_for_mint(rows_le, t0a)
        # buy_vol 60s
        lo = t0a - timedelta(seconds=WINDOW_S)
        vol = 0.0
        cnt = 0
        for r in rows_le:
            if r.side != "buy":
                continue
            if lo <= r.ts <= t0a:
                vol += r.amount_usd
                cnt += 1
        buy60[mint] = (float(vol), int(cnt))
    return q5a, buy60


def fetch_q5b_creates_and_priors(
    mint_t0: dict[str, datetime],
    *,
    client: Any,
    create_limit: int = 200,
    prior_limit: int = 500,
    prior_days: int = 30,
    hours_ago_creates: int | None = None,
) -> dict[str, dict[str, Any]]:
    """2 Bitquery calls → Q5b feats per mint. Missing create → incomplete."""
    from ingestion.pump_constants import PUMP_PROGRAM_ID

    if not mint_t0:
        return {}
    ha = hours_ago_creates if hours_ago_creates is not None else _hours_covering(
        mint_t0, extra_s=prior_days * 86400, pad_h=2
    )
    # Cap hours_ago for FREE plans — prefer covering create; caller may pass smaller
    ha = max(ha, 24)
    body = client.graphql(
        QUERY_CREATES_FOR_MINTS,
        {
            "mints": list(mint_t0.keys()),
            "hoursAgo": min(ha, 24 * 40),  # ~40d max like Dune bounds
            "limit": create_limit,
            "program": PUMP_PROGRAM_ID,
        },
    )
    raw = (((body.get("data") or {}).get("Solana") or {}).get("Instructions")) or []
    creates = parse_bitquery_creates(raw, mint_hint=set(mint_t0.keys()))
    # earliest create per mint ≤ t0
    best: dict[str, CreateRow] = {}
    for c in creates:
        t0 = mint_t0.get(c.mint)
        if t0 is None:
            continue
        t0a = _parse_ts(t0)
        if _parse_ts(c.create_ts) > t0a:
            continue
        prev = best.get(c.mint)
        if prev is None or c.create_ts < prev.create_ts:
            best[c.mint] = c

    creators = sorted({c.creator_pubkey for c in best.values() if c.creator_pubkey})
    prior_rows: list[CreateRow] = []
    if creators:
        body2 = client.graphql(
            QUERY_CREATES_BY_CREATORS,
            {
                "creators": creators,
                "hoursAgo": min(prior_days * 24 + 24, 24 * 40),
                "limit": prior_limit,
                "program": PUMP_PROGRAM_ID,
            },
        )
        raw2 = (((body2.get("data") or {}).get("Solana") or {}).get("Instructions")) or []
        prior_rows = parse_bitquery_creates(raw2, mint_hint=None)

    out: dict[str, dict[str, Any]] = {}
    for mint, t0 in mint_t0.items():
        create = best.get(mint)
        out[mint] = q5b_from_create(create, _parse_ts(t0), prior_creates=prior_rows if creators else [])
    return out


def enrich_q5_for_sightings(
    sightings: list[Any],
    *,
    dry_run: bool,
    client: Any | None = None,
    fixture_path: Path | None = None,
    trade_limit: int = 2000,
    hours_ago: int | None = None,
    enrich_q5a: bool = True,
    enrich_q5b: bool = True,
) -> dict[str, Q5EnrichResult]:
    """Batch enrich. Dry → fixture; live → Bitquery (1–3 calls)."""
    if not sightings:
        return {}
    mints = [s.mint for s in sightings]
    if dry_run or client is None:
        return enrich_q5_from_fixture(mints, path=fixture_path)

    mint_t0 = {
        s.mint: _parse_ts(s.seen_at if hasattr(s, "seen_at") else s.t0_iso) for s in sightings
    }
    by_sight = {s.mint: s for s in sightings}
    results: dict[str, Q5EnrichResult] = {
        m: Q5EnrichResult(mint=m, source="bitquery") for m in mint_t0
    }

    q5a_map: dict[str, dict[str, float | None]] = {}
    buy60_map: dict[str, tuple[float, int]] = {}
    if enrich_q5a:
        q5a_map, buy60_map = fetch_q5a_and_buy60(
            mint_t0, client=client, trade_limit=trade_limit, hours_ago=hours_ago
        )
        for m, feats in q5a_map.items():
            results[m].features.update({c: feats.get(c) for c in Q5A_COLS})
            results[m].q5a_ok = True
            if m in buy60_map:
                results[m].buy_vol_usd_60s, results[m].buy_count_60s = buy60_map[m]
                results[m].features["buy_vol_usd_60s"] = buy60_map[m][0]

    if enrich_q5b:
        q5b_map = fetch_q5b_creates_and_priors(
            mint_t0, client=client, hours_ago_creates=hours_ago
        )
        for m, feats in q5b_map.items():
            s = by_sight.get(m)
            feats = prefer_sighting_meta_name_symbol(
                feats,
                name=getattr(s, "name", None) if s else None,
                symbol=getattr(s, "symbol", None) if s else None,
            )
            try:
                from paper_live.creator_priors import load_creator_prior_index

                feats = fill_meta_from_dune_store_exact(
                    feats, load_creator_prior_index().exact_meta_for_mint(m)
                )
            except Exception:
                pass
            for c in Q5B_COLS:
                results[m].features[c] = feats.get(c)
            for k in ("creator_pubkey", "create_ts", "meta_source"):
                if k in feats:
                    results[m].features[k] = feats[k]
            results[m].q5b_ok = bool(feats.get("q5b_complete"))
            results[m].detail = "q5a+q5b" if results[m].q5a_ok else "q5b"

    for m, r in results.items():
        r.source = "bitquery.q5"
        if r.q5a_ok and r.q5b_ok:
            r.detail = "DEXTradeByTokens+Instructions"
        elif r.q5a_ok:
            r.detail = "DEXTradeByTokens only (q5b incomplete)"
        elif r.q5b_ok:
            r.detail = "Instructions only (q5a incomplete)"
    return results
