"""Paper-live tracker v0 — poll Pump.fun MC band, score ≤T0, journal paper candidates.

NO real trading. Zero look-ahead in scoring (features / score only use ≤T0).
See ``cycle0/paper-live-v0.md``.
"""

from paper_live.config import PaperLiveConfig

__all__ = ["PaperLiveConfig"]
