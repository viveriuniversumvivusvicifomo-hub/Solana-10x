from __future__ import annotations

from verification.dry_v5 import assert_constants_module, assert_mc_single_impl, assert_no_denylist_dupes


def test_constants_and_mc_present():
    assert_constants_module()
    assert_mc_single_impl()


def test_no_denylist_dupes_in_src():
    assert assert_no_denylist_dupes() == []
