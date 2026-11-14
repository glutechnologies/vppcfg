#
# Copyright (c) 2026 Glu Technologies
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# -*- coding: utf-8 -*-
"""Unit tests for L2 VLAN tag rewrites"""

import unittest
from . import l2rewrite

SUBS = "GigabitEthernet1/0/0"


def config():
    """.100 dot1q, .101 QinAD, .102 dot1q, .105 QinAD and .106 dot1q in bd10, with
    explicit rewrites or not; .103 an L2XC source; .104 L3; the untagged
    GigabitEthernet1/0/1 an L2XC target."""
    return {
        "interfaces": {
            SUBS: {
                "sub-interfaces": {
                    100: {"encapsulation": {"dot1q": 100}},
                    101: {"encapsulation": {"dot1ad": 101, "inner-dot1q": 200}},
                    102: {
                        "encapsulation": {"dot1q": 102},
                        "l2-rewrite": {
                            "pop": 1,
                            "push": {"dot1q": 800, "pcp": 5, "dei": True},
                        },
                    },
                    103: {"l2xc": "GigabitEthernet1/0/1"},
                    104: {"encapsulation": {"dot1q": 104}},
                    105: {
                        "encapsulation": {"dot1ad": 105, "inner-dot1q": 300},
                        "l2-rewrite": {
                            "pop": 2,
                            "push": {
                                "dot1ad": 900,
                                "inner-dot1q": 901,
                                "inner-pcp": 7,
                            },
                        },
                    },
                    106: {"encapsulation": {"dot1q": 106}, "l2-rewrite": {}},
                }
            },
            "GigabitEthernet1/0/1": {},
        },
        "bridgedomains": {
            "bd10": {
                "interfaces": [f"{SUBS}.{sub}" for sub in (100, 101, 102, 105, 106)]
            }
        },
    }


class TestL2RewriteMethods(unittest.TestCase):
    def setUp(self):
        self.cfg = config()

    def test_tci(self):
        self.assertEqual(l2rewrite.tci(100), 100)
        self.assertEqual(l2rewrite.tci(801, 5, True), (5 << 13) | (1 << 12) | 801)
        self.assertEqual(l2rewrite.tci(4095, 7, True), 0xFFFF)

    def test_number_of_tags(self):
        self.assertEqual(l2rewrite.get_number_of_tags(self.cfg, SUBS), 0)
        self.assertEqual(l2rewrite.get_number_of_tags(self.cfg, f"{SUBS}.100"), 1)
        self.assertEqual(l2rewrite.get_number_of_tags(self.cfg, f"{SUBS}.101"), 2)
        self.assertEqual(l2rewrite.get_number_of_tags(self.cfg, f"{SUBS}.103"), 1)

    def test_defaults(self):
        ## Bridge-domain members and L2XC sources pop the tags of their encapsulation.
        self.assertEqual(
            l2rewrite.get_l2_rewrite(self.cfg, f"{SUBS}.100"), {"pop": 1, "push": []}
        )
        self.assertEqual(
            l2rewrite.get_l2_rewrite(self.cfg, f"{SUBS}.101"), {"pop": 2, "push": []}
        )
        self.assertEqual(
            l2rewrite.get_l2_rewrite(self.cfg, f"{SUBS}.103"), {"pop": 1, "push": []}
        )
        ## Not managed: L3, an L2XC target without l2-rewrite, an unknown interface.
        self.assertIsNone(l2rewrite.get_l2_rewrite(self.cfg, f"{SUBS}.104"))
        self.assertIsNone(l2rewrite.get_l2_rewrite(self.cfg, "GigabitEthernet1/0/1"))
        self.assertIsNone(l2rewrite.get_l2_rewrite(self.cfg, "GigabitEthernet9/0/0"))

    def test_explicit(self):
        self.assertEqual(
            l2rewrite.get_l2_rewrite(self.cfg, f"{SUBS}.102"),
            {"pop": 1, "push": [("dot1q", l2rewrite.tci(800, 5, True))]},
        )
        self.assertEqual(
            l2rewrite.get_l2_rewrite(self.cfg, f"{SUBS}.105"),
            {"pop": 2, "push": [("dot1ad", 900), ("dot1q", l2rewrite.tci(901, 7))]},
        )
        ## An empty l2-rewrite replaces the default pop by nothing.
        self.assertEqual(
            l2rewrite.get_l2_rewrite(self.cfg, f"{SUBS}.106"), {"pop": 0, "push": []}
        )

    def test_interfaces(self):
        self.assertEqual(
            sorted(l2rewrite.get_l2_rewrite_interfaces(self.cfg)),
            sorted(f"{SUBS}.{sub}" for sub in (100, 101, 102, 103, 105, 106)),
        )

    def test_validate(self):
        self.assertEqual(l2rewrite.validate_l2_rewrites(self.cfg), (True, []))
        subs = self.cfg["interfaces"][SUBS]["sub-interfaces"]
        subs[104]["l2-rewrite"] = {"pop": 1}
        subs[100]["l2-rewrite"] = {"pop": 2}
        result, msgs = l2rewrite.validate_l2_rewrites(self.cfg)
        self.assertFalse(result)
        self.assertEqual(
            sorted(msgs),
            [
                f"interface {SUBS}.100 l2-rewrite pops 2 tags, but its encapsulation has 1",
                f"interface {SUBS}.104 l2-rewrite needs an L2 interface",
            ],
        )
