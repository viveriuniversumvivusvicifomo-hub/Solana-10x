"""Poller loop paper-live v0 (~10s): sight → enrich ≤T0 → score → ultra-select paper → followup.

Default feed: Pump.fun frontend-api-v3 (``--feed pump``).
Default enrich: Helius Enhanced ≤T0 trades (``--enrich-via helius``). Bitquery optional.

Zero look-ahead: score solo con features del snapshot T0.
Missing FEATURE_SETS['+q5b'] → skip (no substitutes) when score_mode=histgb_q5b.
Entry default: trainQ top1% + max_per_hour (NOT top-K every batch) — see entry.py.
NO trading real.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from paper_live.buy_vol import enrich_buy_vol_for_sightings
from paper_live.config import PaperLiveConfig
from paper_live.entry import EntryGate
from paper_live.features_t0 import assert_no_lookahead_keys, features_at_t0
from paper_live.feed import MintSighting, poll_bitquery, poll_pump, poll_sample
from paper_live.followup import FollowupTracker
from paper_live.journal import Journal
from paper_live.q5_enrich import enrich_q5_for_sightings
from paper_live.multi_score import MultiPaperScorer
from paper_live.score import PaperScorer


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CycleStats:
    cycle: int
    n_polled: int
    n_new: int
    n_paper_entered: int
    n_skipped_missing_vol: int
    n_skipped_incomplete_q5b: int
    n_skipped_below_threshold: int
    n_skipped_capacity: int
    n_followup: int
    source: str
    errors: list[str]


class PaperLiveRunner:
    def __init__(self, cfg: PaperLiveConfig) -> None:
        cfg.ensure_dirs()
        self.cfg = cfg
        self.journal = Journal(
            sqlite_path=cfg.sqlite_path,
            state_path=cfg.state_path,
            candidates_csv=cfg.data_dir / "candidates.csv",
            followup_csv=cfg.data_dir / "followup.csv",
            sightings_csv=cfg.data_dir / "sightings.csv",
        )
        self.scorer = PaperScorer(
            cfg.score_mode,
            allow_q5b_fallback=cfg.allow_q5b_fallback,
            require_t0_refined=getattr(cfg, "require_t0_refined", True),
            max_age_s=getattr(cfg, "max_age_s", 86_400.0),
            require_pyth_when_key=getattr(cfg, "require_pyth_when_key", True),
        )
        # Opt-in multi-lane: histgb primary + lite explore (see score-mode-lite cycle0 doc).
        modes = (getattr(cfg, "parallel_score_modes", "") or "").strip()
        if getattr(cfg, "enable_lite_lane", False) and "lite" not in modes:
            modes = ",".join(x for x in (cfg.score_mode, "lite") if x)
        if not modes:
            modes = cfg.score_mode
        thr_map: dict[str, float | None] = {cfg.score_mode: cfg.score_threshold}
        if "lite" in modes:
            thr_map["lite"] = getattr(cfg, "score_threshold_lite", 0.55)
        self.multi_scorer = MultiPaperScorer(
            modes,
            primary_lane=cfg.score_mode if cfg.score_mode in modes else modes.split(",")[0].strip(),
            thresholds=thr_map,
            allow_q5b_fallback=cfg.allow_q5b_fallback,
            require_t0_refined=getattr(cfg, "require_t0_refined", True),
            max_age_s=getattr(cfg, "max_age_s", 86_400.0),
            require_pyth_when_key=getattr(cfg, "require_pyth_when_key", True),
        )
        self._parallel_modes = [m.strip() for m in modes.split(",") if m.strip()]
        self.entry_gate = EntryGate(
            entry_rule=cfg.entry_rule,
            score_threshold=cfg.score_threshold,
            train_top_frac=cfg.train_top_frac,
            allow_non_train_threshold=getattr(cfg, "allow_non_train_threshold", False),
            max_per_hour=cfg.max_per_hour,
            top_k=cfg.top_k,
            score_mode=cfg.score_mode,
        )
        self.entry_gate_lite = EntryGate(
            entry_rule=cfg.entry_rule,
            score_threshold=getattr(cfg, "score_threshold_lite", 0.55),
            train_top_frac=cfg.train_top_frac,
            allow_non_train_threshold=True,
            max_per_hour=getattr(cfg, "max_per_hour_lite", cfg.max_per_hour),
            top_k=cfg.top_k,
            score_mode="lite",
        )
        self.followup = FollowupTracker(self.journal)
        self.state = self.journal.load_state()
        self.followup.seed_from_journal()
        self._bq_client: Any = None
        self._pump_client: Any = None
        self._helius_client: Any = None

    def _resolve_enrich_via(self) -> str:
        via = (self.cfg.enrich_via or "auto").lower()
        if via == "auto":
            # Path A live (2026-10-02): Pump MC+T0 default; Bitquery feed → bitquery
            return "bitquery" if self.cfg.feed == "bitquery" else "pump"
        return via

    def _get_bq_client(self) -> Any:
        if self._bq_client is None:
            from ingestion.bitquery import BitqueryClient

            self._bq_client = BitqueryClient(max_calls=self.cfg.max_calls_live)
        return self._bq_client

    def _get_pump_client(self) -> Any:
        if self._pump_client is None:
            from ingestion.pump_frontend import PumpFrontendClient

            self._pump_client = PumpFrontendClient()
        return self._pump_client

    def _get_helius_client(self) -> Any:
        if self._helius_client is None:
            from ingestion.helius_enhanced import HeliusEnhanced
            from paper_live.config import (
                DEFAULT_HELIUS_HTTP_TIMEOUT_S_LIVE,
                DEFAULT_HELIUS_MAX_BACKOFF_S_LIVE,
                DEFAULT_HELIUS_MAX_CALLS_LIVE,
                DEFAULT_HELIUS_MAX_PAGES_LIVE,
                DEFAULT_HELIUS_MAX_RETRIES_429_LIVE,
            )

            # Live FAST: tight pages (5); session soft must NOT kill the daemon after a few mints.
            # Prefer CLI --max-calls when raised; else DEFAULT_HELIUS_MAX_CALLS_LIVE.
            # Shorter httpx / fewer 429 retries than offline recovery (fail-soft latency).
            soft = max(
                DEFAULT_HELIUS_MAX_CALLS_LIVE,
                int(getattr(self.cfg, "max_calls_live", 0) or 0),
                DEFAULT_HELIUS_MAX_PAGES_LIVE * max(4, min(self.cfg.top_k, 10)) * 2,
            )
            self._helius_client = HeliusEnhanced(
                max_calls=soft,
                timeout_s=DEFAULT_HELIUS_HTTP_TIMEOUT_S_LIVE,
                max_retries_429=DEFAULT_HELIUS_MAX_RETRIES_429_LIVE,
                max_backoff_s=DEFAULT_HELIUS_MAX_BACKOFF_S_LIVE,
            )
        return self._helius_client

    def close(self) -> None:
        if self._bq_client is not None:
            self._bq_client.close()
            self._bq_client = None
        if self._pump_client is not None:
            self._pump_client.close()
            self._pump_client = None
        if self._helius_client is not None:
            self._helius_client.close()
            self._helius_client = None
        self.journal.save_state(self.state)

    def poll_once(self) -> list[MintSighting]:
        if self.cfg.live and not self.cfg.dry_run:
            if self.cfg.feed == "bitquery":
                sightings, _log = poll_bitquery(
                    limit=50,
                    hours_ago=self.cfg.hours_ago,
                    mc_lo=self.cfg.mc_lo,
                    mc_hi=self.cfg.mc_hi,
                    client=self._get_bq_client(),
                )
                return sightings
            # default: pump frontend
            sightings, _log = poll_pump(
                mc_lo=self.cfg.mc_lo,
                mc_hi=self.cfg.mc_hi,
                limit=50,
                max_pages=2,
                client=self._get_pump_client(),
            )
            return sightings
        offset = int(self.state.get("dry_offset") or 0)
        src = (
            "dry_run.pump_sample"
            if "pump_frontend" in str(self.cfg.sample_path)
            else "dry_run.sample"
        )
        batch = poll_sample(
            self.cfg.sample_path,
            offset=offset,
            batch=max(self.cfg.top_k, 10),
            source=src,
        )
        self.state["dry_offset"] = offset + len(batch)
        return batch

    def _enrich(self, new_sightings: list[MintSighting]) -> dict[str, Any]:
        """Prefer full +q5b enrich; fall back to buy_vol-only if enrich_q5 off."""
        if not new_sightings:
            return {}
        dry = self.cfg.dry_run or not self.cfg.live
        via = self._resolve_enrich_via()
        if self.cfg.enrich_q5:
            if dry:
                # Pump sample dry: derive Q5b from coin fields in sample (0 network).
                # Bitquery sample dry: use q5_live_fixture for full +q5b vectors.
                # Path A default = pump. Helius dry only when explicitly --enrich-via helius.
                use_helius_offline = via == "helius"
                use_pump_offline = via in ("pump", "auto")
                if via == "helius" or (use_helius_offline and via != "pump"):
                    from paper_live.helius_enrich import enrich_helius_for_sightings
                    from paper_live.config import SAMPLE_HELIUS_TX_FIXTURE

                    return enrich_helius_for_sightings(
                        new_sightings,
                        client=None,
                        dry_run=True,
                        fixture_path=SAMPLE_HELIUS_TX_FIXTURE,
                        fetch_priors=False,
                        sol_usd=self.cfg.sol_usd_ref,
                    )
                if use_pump_offline or via == "pump":
                    from paper_live.pump_enrich import enrich_pump_for_sightings

                    return enrich_pump_for_sightings(
                        new_sightings,
                        client=None,
                        fetch_priors=False,  # no network in dry
                        fetch_trades=False,
                        dry_run=True,
                    )
                return enrich_q5_for_sightings(
                    new_sightings,
                    dry_run=True,
                    client=None,
                    fixture_path=self.cfg.q5_fixture_path,
                    trade_limit=self.cfg.q5a_trade_limit,
                    hours_ago=self.cfg.q5a_hours_ago,
                    enrich_q5a=self.cfg.enrich_q5a,
                    enrich_q5b=self.cfg.enrich_q5b,
                )
            if via == "pump":
                from paper_live.pump_enrich import enrich_pump_for_sightings

                return enrich_pump_for_sightings(
                    new_sightings,
                    client=self._get_pump_client(),
                    fetch_priors=self.cfg.enrich_q5b,
                    fetch_trades=True,
                    dry_run=False,
                )
            if via == "helius":
                from paper_live.helius_enrich import enrich_helius_for_sightings

                from paper_live.config import (
                    DEFAULT_HELIUS_MAX_PAGES_LIVE,
                    DEFAULT_HELIUS_MINT_TIMEOUT_S_LIVE,
                )

                return enrich_helius_for_sightings(
                    new_sightings,
                    client=self._get_helius_client(),
                    pump_client=self._get_pump_client(),
                    dry_run=False,
                    fetch_priors=self.cfg.enrich_q5b,
                    sol_usd=None,  # Pyth as-of T0 (fallback Jupiter/CG); cfg.sol_usd_ref = oracle fallback
                    refine_t0=True,
                    max_pages_per_mint=DEFAULT_HELIUS_MAX_PAGES_LIVE,
                    sol_usd_as_of_t0=True,
                    mint_timeout_s=DEFAULT_HELIUS_MINT_TIMEOUT_S_LIVE,
                    heartbeat=True,
                )
            client = self._get_bq_client()
            return enrich_q5_for_sightings(
                new_sightings,
                dry_run=False,
                client=client,
                fixture_path=self.cfg.q5_fixture_path,
                trade_limit=self.cfg.q5a_trade_limit,
                hours_ago=self.cfg.q5a_hours_ago,
                enrich_q5a=self.cfg.enrich_q5a,
                enrich_q5b=self.cfg.enrich_q5b,
            )
        if not self.cfg.enrich_buy_vol:
            return {}
        if dry:
            return enrich_buy_vol_for_sightings(
                new_sightings,
                dry_run=True,
                client=None,
                fixture_path=self.cfg.buy_vol_fixture_path,
                trade_limit=self.cfg.buy_vol_trade_limit,
                hours_ago=self.cfg.q5a_hours_ago,
            )
        if via == "pump":
            # no buy_vol without trades — return empty → skip_missing_vol
            return {}
        client = self._get_bq_client()
        return enrich_buy_vol_for_sightings(
            new_sightings,
            dry_run=False,
            client=client,
            fixture_path=self.cfg.buy_vol_fixture_path,
            trade_limit=self.cfg.buy_vol_trade_limit,
            hours_ago=self.cfg.q5a_hours_ago,
        )

    def process_sightings(self, sightings: list[MintSighting]) -> tuple[int, int, int, int, int, int]:
        """Registra nuevos; ultra-select paper (trainQ + capacity), not top-K every batch.

        Returns:
            n_new, n_entered, n_skip_vol, n_skip_q5b, n_skip_below_thr, n_skip_capacity
        """
        known = self.journal.known_mints()
        new_sightings = [s for s in sightings if s.mint not in known]
        enriched = self._enrich(new_sightings)

        scored: list[tuple[float, MintSighting, dict[str, Any], Any]] = []
        scored_lite: list[tuple[float, MintSighting, dict[str, Any], Any]] = []
        n_new = 0
        n_skip_vol = 0
        n_skip_q5b = 0
        for s in new_sightings:
            er = enriched.get(s.mint)
            q5_extras: dict[str, Any] = {}
            bv = None
            src = "unavailable"
            bcount = None
            if er is not None:
                # Q5EnrichResult
                if hasattr(er, "features"):
                    q5_extras = dict(er.features)
                    bv = er.buy_vol_usd_60s
                    src = er.source
                    bcount = er.buy_count_60s
                else:
                    # BuyVolResult legacy
                    bv = er.buy_vol_usd_60s
                    src = er.source
                    bcount = er.buy_count_60s
            # Prefer C1–C6 refined T0/MC from hybrid enrich when available
            t0_ts = s.t0_iso
            mc_t0 = s.mc_usd
            if er is not None and getattr(er, "t0_iso", None):
                t0_ts = er.t0_iso
            if er is not None and getattr(er, "mc_usd_t0", None) is not None:
                mc_t0 = float(er.mc_usd_t0)
            feats = features_at_t0(
                s,
                dry_run=self.cfg.dry_run or not self.cfg.live,
                buy_vol_usd_60s=bv,
                buy_vol_source=src,
                buy_count_60s=bcount,
                q5_extras=q5_extras or None,
            )
            feats["t0_ts"] = t0_ts
            feats["mc_usd_t0"] = mc_t0
            assert_no_lookahead_keys(feats)
            multi = self.multi_scorer.score_all(feats)
            scores_doc = multi.as_scores_json()
            primary = multi.primary
            sr = primary.result if primary is not None else self.scorer.score(feats)
            lite_lane = multi.lanes.get("lite")
            score_lite = (
                None
                if lite_lane is None or lite_lane.skipped
                else float(lite_lane.score)
            )
            inserted = self.journal.record_sighting(
                mint=s.mint,
                t0_ts=t0_ts,
                mc_usd_t0=mc_t0,
                name=s.name,
                symbol=s.symbol,
                source=s.source,
                features=feats,
                score=None if sr.skipped else sr.score,
                score_mode=sr.mode,
                paper_candidate=False,
                scores_json=scores_doc,
                score_lite=score_lite,
            )
            if not inserted:
                continue
            n_new += 1
            known.add(s.mint)
            if lite_lane is not None and not lite_lane.skipped:
                scored_lite.append((lite_lane.score, s, feats, lite_lane.result))
            if sr.skipped:
                if sr.mode in (
                    "skip_incomplete_q5b",
                    "skip_t0_not_refined",
                    "skip_prior_not_train",
                    "skip_age_anomaly",
                    "skip_sol_usd_not_pyth",
                    "skip_capture_not_scoreable",
                ):
                    n_skip_q5b += 1
                elif sr.mode in ("skip_missing_buy_vol", "skip_missing_model"):
                    n_skip_vol += 1
                else:
                    n_skip_vol += 1
                continue
            scored.append((sr.score, s, feats, sr))

        scored.sort(key=lambda x: (-x[0], x[1].t0_iso, x[1].mint))
        journal_ats = self.journal.recent_paper_entered_at()
        accepted, counters = self.entry_gate.filter_scored_batch(
            scored,
            journal_entered_at=journal_ats,
        )
        n_skip_thr = int(counters["n_skip_below_threshold"])
        n_skip_cap = int(counters["n_skip_capacity"])
        n_entered = 0
        for rank, (score, s, feats, sr) in enumerate(accepted, start=1):
            ok = self.journal.enter_paper(
                mint=s.mint,
                t0_ts=str(feats.get("t0_ts") or s.t0_iso),
                mc_usd_t0=float(feats.get("mc_usd_t0") if feats.get("mc_usd_t0") is not None else s.mc_usd),
                score=score,
                score_mode=sr.mode,
                rank_at_entry=rank,
                features=feats,
            )
            if ok:
                n_entered += 1
                self.followup.max_mc[s.mint] = s.mc_usd
        # Explore lane (lite) — separate stream; never weakens histgb gates.
        if scored_lite and "lite" in getattr(self, "_parallel_modes", []):
            scored_lite.sort(key=lambda x: (-x[0], x[1].t0_iso, x[1].mint))
            accepted_l, _c_l = self.entry_gate_lite.filter_scored_batch(
                scored_lite,
                journal_entered_at=[],  # capacity via lite table only (stub: no hist)
            )
            for rank, (score, s, feats, sr) in enumerate(accepted_l, start=1):
                self.journal.enter_paper_lite(
                    mint=s.mint,
                    t0_ts=str(feats.get("t0_ts") or s.t0_iso),
                    mc_usd_t0=float(
                        feats.get("mc_usd_t0")
                        if feats.get("mc_usd_t0") is not None
                        else s.mc_usd
                    ),
                    score=score,
                    score_mode=sr.mode,
                    rank_at_entry=rank,
                    features=feats,
                )
        return n_new, n_entered, n_skip_vol, n_skip_q5b, n_skip_thr, n_skip_cap

    def run_followup(self, cycle: int) -> int:
        if self.cfg.dry_run or not self.cfg.live:
            rows = self.followup.dry_run_step(cycle=cycle)
            return len(rows)
        opens = self.journal.open_candidates()
        if not opens:
            return 0
        try:
            if self.cfg.feed == "bitquery" or self._resolve_enrich_via() == "bitquery":
                found = self.followup.poll_bitquery_mcs(
                    [r["mint"] for r in opens],
                    client=self._get_bq_client(),
                )
            else:
                found = self.followup.poll_pump_mcs(
                    [r["mint"] for r in opens],
                    client=self._get_pump_client(),
                )
        except Exception as e:  # noqa: BLE001
            self.state.setdefault("followup_errors", [])
            err = str(e)[:200]
            self.state["followup_errors"] = (self.state.get("followup_errors") or [])[-5:] + [err]
            return 0
        n = 0
        by_mint = {r["mint"]: r for r in opens}
        for mint, mc in found.items():
            self.followup.update_mc(mint, mc, float(by_mint[mint]["mc_usd_t0"]))
            n += 1
        return n

    def run_cycle(self, cycle: int) -> CycleStats:
        errors: list[str] = []
        if self.cfg.live and not self.cfg.dry_run:
            source = f"live.{self.cfg.feed}"
        else:
            source = "dry_run.sample"
        try:
            sightings = self.poll_once()
        except Exception as e:  # noqa: BLE001
            errors.append(str(e)[:300])
            sightings = []
        n_new = n_paper = n_skip_vol = n_skip_q5b = n_skip_thr = n_skip_cap = 0
        try:
            n_new, n_paper, n_skip_vol, n_skip_q5b, n_skip_thr, n_skip_cap = self.process_sightings(
                sightings
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"process: {str(e)[:250]}")
        n_fu = 0
        try:
            n_fu = self.run_followup(cycle)
        except Exception as e:  # noqa: BLE001
            errors.append(f"followup: {str(e)[:200]}")
        self.state["cycles"] = int(self.state.get("cycles") or 0) + 1
        self.state["last_poll_at"] = _utcnow().isoformat(timespec="milliseconds")
        self.journal.save_state(self.state)
        return CycleStats(
            cycle=cycle,
            n_polled=len(sightings),
            n_new=n_new,
            n_paper_entered=n_paper,
            n_skipped_missing_vol=n_skip_vol,
            n_skipped_incomplete_q5b=n_skip_q5b,
            n_skipped_below_threshold=n_skip_thr,
            n_skipped_capacity=n_skip_cap,
            n_followup=n_fu,
            source=source,
            errors=errors,
        )

    def run(self, *, max_cycles: int | None = None) -> dict[str, Any]:
        """Loop principal. max_cycles=None → cfg.cycles o infinito si 0."""
        limit = max_cycles if max_cycles is not None else self.cfg.cycles
        infinite = limit <= 0
        cycle = 0
        stats: list[dict[str, Any]] = []
        try:
            while infinite or cycle < limit:
                cycle += 1
                t_cycle = time.monotonic()
                st = self.run_cycle(cycle)
                wall_s = time.monotonic() - t_cycle
                stats.append(st.__dict__)
                print(
                    f"[paper-live] cycle={st.cycle} source={st.source} "
                    f"polled={st.n_polled} new={st.n_new} paper={st.n_paper_entered} "
                    f"skip_vol={st.n_skipped_missing_vol} skip_q5b={st.n_skipped_incomplete_q5b} "
                    f"skip_below_thr={st.n_skipped_below_threshold} "
                    f"skip_cap={st.n_skipped_capacity} "
                    f"followup={st.n_followup} wall_s={wall_s:.1f} errors={st.errors}",
                    flush=True,
                )
                if not infinite and cycle >= limit:
                    break
                sleep_s = 0.05 if self.cfg.dry_run else self.cfg.poll_interval_s
                time.sleep(sleep_s)
                if self.cfg.live and not self.cfg.dry_run and self.cfg.feed == "bitquery":
                    client = self._bq_client
                    if client is not None and getattr(client, "_n", 0) >= getattr(
                        client, "_max_calls", 10**9
                    ):
                        print("[paper-live] max_calls Bitquery alcanzado — stop", flush=True)
                        break
                if self.cfg.live and not self.cfg.dry_run and self._resolve_enrich_via() == "helius":
                    h = self._helius_client
                    if h is not None and getattr(h, "_max_calls", None) is not None:
                        if h.n_calls >= h._max_calls:
                            print("[paper-live] max_calls Helius Enhanced alcanzado — stop", flush=True)
                            break
        finally:
            self.close()
        summary = self.journal.summary()
        summary["cycles_run"] = cycle
        summary["stats"] = stats
        summary["score_mode"] = self.cfg.score_mode
        summary["parallel_score_modes"] = getattr(self, "_parallel_modes", [self.cfg.score_mode])
        summary["feed"] = self.cfg.feed
        summary["enrich_via"] = self._resolve_enrich_via()
        summary["dry_run"] = self.cfg.dry_run
        summary["live"] = self.cfg.live
        summary["enrich_q5"] = self.cfg.enrich_q5
        summary["enrich_buy_vol"] = self.cfg.enrich_buy_vol
        summary["allow_q5b_fallback"] = self.cfg.allow_q5b_fallback
        summary["entry"] = self.entry_gate.describe()
        summary["n_skipped_below_threshold_total"] = sum(
            int(s.get("n_skipped_below_threshold") or 0) for s in stats
        )
        summary["n_skipped_capacity_total"] = sum(
            int(s.get("n_skipped_capacity") or 0) for s in stats
        )
        summary["trading"] = False
        return summary
