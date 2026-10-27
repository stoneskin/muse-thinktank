"""Unit tests for tt/members.py scoring.

The availability formula in this worktree (read from the file, not
from memory) is:

    availability = success_rate * (1 / (1 + mean_latency / 120))

i.e. the latency divisor is 120 — NOT 300 (that is another branch).
Docstring anchors: 60s -> 0.67x, 120s -> 0.5x (at success_rate 1.0).
"""

import unittest

from tt.members import (
    MEMBER_MIN_SCORE,
    availability,
    record_member,
    select_members,
)


def _state(ok, lat):
    return {"m": {"ok": list(ok), "lat": list(lat),
                  "judge_accept": 0, "judge_reject": 0, "judge_fail": 0}}


class TestAvailability(unittest.TestCase):
    def test_no_history_returns_1(self):
        self.assertEqual(availability("m", {}), 1.0)
        self.assertEqual(availability("m", {"m": {"ok": [], "lat": []}}), 1.0)

    def test_perfect_fast_model_scores_1(self):
        self.assertAlmostEqual(availability("m", _state([True, True], [0, 0])),
                               1.0)

    def test_latency_120_halves_score(self):
        # 1 / (1 + 120/120) = 0.5
        self.assertAlmostEqual(availability("m", _state([True], [120.0])),
                               0.5)

    def test_latency_60_gives_two_thirds(self):
        # 1 / (1 + 60/120) = 1 / 1.5 = 2/3 (~0.67, per the docstring)
        self.assertAlmostEqual(availability("m", _state([True], [60.0])),
                               2.0 / 3.0)

    def test_latency_240_gives_one_third(self):
        # 1 / (1 + 240/120) = 1/3
        self.assertAlmostEqual(availability("m", _state([True], [240.0])),
                               1.0 / 3.0)

    def test_success_rate_dominates(self):
        # sr = 1/2, no latency penalty -> 0.5
        self.assertAlmostEqual(
            availability("m", _state([True, False], [0.0, 0.0])), 0.5)

    def test_success_rate_times_latency_penalty(self):
        # sr = 2/3, mean latency 120 -> penalty 0.5 -> 1/3
        self.assertAlmostEqual(
            availability("m", _state([True, True, False],
                                     [120.0, 120.0, 120.0])),
            1.0 / 3.0)

    def test_mean_latency_is_averaged(self):
        # mean latency (0 + 240) / 2 = 120 -> penalty 0.5 at sr 1.0
        self.assertAlmostEqual(
            availability("m", _state([True, True], [0.0, 240.0])), 0.5)

    def test_record_member_feeds_availability(self):
        state = {}
        record_member(state, "m", True, 120.0)
        record_member(state, "m", True, 120.0)
        self.assertAlmostEqual(availability("m", state), 0.5)


class TestSelectMembers(unittest.TestCase):
    def test_threshold_filters_below_min_score(self):
        self.assertEqual(MEMBER_MIN_SCORE, 0.6)
        state = {"slow": {"ok": [True], "lat": [120.0],
                          "judge_accept": 0, "judge_reject": 0,
                          "judge_fail": 0}}
        kept, dropped = select_members(["fast", "slow"], state,
                                       {"fast": 1.0, "slow": 1.0})
        # fast: cap 1.0 x avail 1.0 = 1.0 -> kept
        # slow: cap 1.0 x avail 0.5 = 0.5 < 0.6 -> dropped
        self.assertEqual(kept, ["fast"])
        self.assertEqual(dropped, ["slow"])

    def test_capability_scales_score(self):
        # cap 0.5 x avail 1.0 = 0.5 < 0.6 -> dropped even with no latency
        kept, dropped = select_members(["weak"], {}, {"weak": 0.5})
        self.assertEqual(kept, [])
        self.assertEqual(dropped, ["weak"])

    def test_score_exactly_at_threshold_is_kept(self):
        # cap 0.6 x avail 1.0 = 0.6 >= 0.6 -> kept
        kept, dropped = select_members(["edge"], {}, {"edge": 0.6})
        self.assertEqual(kept, ["edge"])
        self.assertEqual(dropped, [])

    def test_missing_capability_defaults_to_1(self):
        kept, dropped = select_members(["new"], {}, {})
        self.assertEqual(kept, ["new"])
        self.assertEqual(dropped, [])


if __name__ == "__main__":
    unittest.main()
