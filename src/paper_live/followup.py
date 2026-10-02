"""Follow-up MC poller post-T0 → hit_10x_30d (paper label tracking).

Importante: follow-up **nunca** vuelve al scorer. Solo actualiza journal labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paper_live.config import HIT_10X_MULTIPLE, MC_HI, MC_LO
from paper_live.journal import Journal


@dataclass
class FollowupTracker:
    """Mantiene max_mc_after_t0 por mint paper; dry-run puede sintetizar path."""

    journal: Journal
    max_mc: dict[str, float] = field(default_factory=dict)

    def seed_from_journal(self) -> None:
        for row in self.journal.open_candidates():
            mint = row["mint"]
            if mint not in self.max_mc:
                self.max_mc[mint] = float(row["mc_usd_t0"])

    def update_mc(self, mint: str, mc_usd: float, mc_usd_t0: float) -> dict[str, Any]:
        prev = self.max_mc.get(mint, mc_usd_t0)
        # Solo post-T0: no bajar el max observado
        new_max = max(prev, mc_usd)
        self.max_mc[mint] = new_max
        return self.journal.record_followup(
            mint=mint,
            mc_usd=mc_usd,
            mc_usd_t0=mc_usd_t0,
            max_mc_after_t0=new_max,
        )

    def dry_run_step(
        self,
        *,
        cycle: int,
        growth: float = 1.15,
    ) -> list[dict[str, Any]]:
        """Avanza MC sintético para smoke (no es predicción; solo ejercita journal)."""
        out: list[dict[str, Any]] = []
        for row in self.journal.open_candidates():
            mint = row["mint"]
            t0 = float(row["mc_usd_t0"])
            cur = self.max_mc.get(mint, t0)
            # path sintético: algunos crecen hacia 10x
            h = sum(ord(c) for c in mint) % 7
            if h >= 5:
                nxt = min(cur * growth, t0 * (HIT_10X_MULTIPLE + 2))
            else:
                nxt = cur * (0.98 + 0.01 * (cycle % 3))
            out.append(self.update_mc(mint, nxt, t0))
        return out

    def poll_bitquery_mcs(
        self,
        mints: list[str],
        *,
        client: Any = None,
    ) -> dict[str, float]:
        """Intenta refrescar MC de mints abiertos.

        Gap: la query Trading.Pairs de cycle0 filtra por banda 8–20k; mints que
        ya salieron de banda no aparecen. Scaffold: re-poll banda ancha + overlap.
        """
        from ingestion.bitquery import BitqueryClient, fetch_pump_mc_candidates

        owns = client is None
        # Banda ancha solo para follow-up (no para captura/scoring)
        client = client or BitqueryClient(max_calls=1)
        try:
            rows, _log = fetch_pump_mc_candidates(
                limit=100,
                hours_ago=24,
                mc_lo=1_000.0,
                mc_hi=5_000_000.0,
                client=client,
            )
            want = set(mints)
            found = {
                r["mint"]: float(r["mc_usd"])
                for r in rows
                if r.get("mint") in want and r.get("mc_usd") is not None
            }
            return found
        finally:
            if owns:
                client.close()

    def poll_pump_mcs(
        self,
        mints: list[str],
        *,
        client: Any = None,
    ) -> dict[str, float]:
        """Refresh MC for open paper mints via Pump frontend band poll + mint overlap.

        Same limitation as Bitquery follow-up: only mints still in/near the polled
        pages appear. No per-mint GET (``/coins/{mint}`` 404 on current v3).
        """
        from ingestion.pump_frontend import PumpFrontendClient, fetch_pump_mc_band

        want = set(mints)
        owns = client is None
        client = client or PumpFrontendClient()
        try:
            # Wide band so graduated-from-8k–20k mints can still match if listed
            rows, _log = fetch_pump_mc_band(
                mc_lo=1_000.0,
                mc_hi=500_000.0,
                limit=50,
                max_pages=3,
                incomplete_only=False,
                client=client,
            )
            found: dict[str, float] = {}
            for r in rows:
                m = r.get("mint")
                mc = r.get("mc_usd")
                if m in want and mc is not None:
                    found[str(m)] = float(mc)
            return found
        finally:
            if owns:
                client.close()


def in_capture_band(mc: float, lo: float = MC_LO, hi: float = MC_HI) -> bool:
    return lo <= mc <= hi
