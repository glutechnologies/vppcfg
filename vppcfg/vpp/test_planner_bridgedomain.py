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
"""Unit tests for the bridgedomain members of the planner and the dumper, against a
VPP configuration cache filled by hand instead of read from a running VPP."""

import sys
import types
import unittest
from types import SimpleNamespace

try:
    import vpp_papi  # pylint: disable=unused-import
except ModuleNotFoundError:
    ## Neither the planner nor the dumper talks to VPP until it reads its config.
    sys.modules["vpp_papi"] = types.SimpleNamespace(
        VPPApiClient=None, VPPApiJSONFiles=None, MACAddress=None
    )

# pylint: disable=wrong-import-position
from .planner import Planner
from .dumper import Dumper

NO_BVI = 2**32 - 1


def bridge(bd_id, members):
    """A bridge_domain_details of VPP, with default settings and the given
    (sw_if_index, shg) members."""
    return SimpleNamespace(
        bd_id=bd_id,
        bd_tag="",
        learn=True,
        flood=True,
        uu_flood=True,
        forward=True,
        arp_term=False,
        arp_ufwd=False,
        mac_age=0,
        bvi_sw_if_index=NO_BVI,
        sw_if_details=[
            SimpleNamespace(sw_if_index=idx, shg=shg) for idx, shg in members
        ],
    )


def fill_cache(vpp, bridges):
    """Interfaces 1-3 are GigabitEthernet1/0/0.100-102, and the given bridges."""
    for idx in (1, 2, 3):
        name = f"GigabitEthernet1/0/0.{99 + idx}"
        vpp.cache["interfaces"][idx] = SimpleNamespace(
            sw_if_index=idx,
            interface_name=name,
            tag="",
            sub_id=99 + idx,
            ## The dumper exports interfaces with 0, 1 or 2 tags; these are left out
            ## of its interfaces, as only their bridge membership is tested.
            sub_number_of_tags=3,
            mtu=[1500, 0, 0, 0],
        )
        vpp.cache["interface_names"][name] = idx
    for bridge_details in bridges:
        vpp.cache["bridgedomains"][bridge_details.bd_id] = bridge_details
    vpp.cache_read = True


CONFIG = {
    "interfaces": {
        "GigabitEthernet1/0/0": {
            "sub-interfaces": {
                100: {"encapsulation": {"dot1q": 100}},
                101: {"encapsulation": {"dot1q": 101}},
                102: {"encapsulation": {"dot1q": 102}},
            }
        }
    },
    "bridgedomains": {
        "bd10": {
            "interfaces": [
                "GigabitEthernet1/0/0.100",
                "GigabitEthernet1/0/0.101",
                "GigabitEthernet1/0/0.102",
            ],
            "split-horizon": {
                "GigabitEthernet1/0/0.101": 1,
                "GigabitEthernet1/0/0.102": 1,
            },
        }
    },
}


class TestPlannerSplitHorizon(unittest.TestCase):
    def sync(self, cfg, bridges):
        planner = Planner(cfg)
        fill_cache(planner.vpp, bridges)
        self.assertTrue(planner._sync_bridgedomains())
        return planner.cli["sync"]

    def test_new_members_get_their_group(self):
        cli = self.sync(CONFIG, [])
        self.assertEqual(
            cli,
            [
                "set interface l2 bridge GigabitEthernet1/0/0.100 10",
                "set interface l2 tag-rewrite GigabitEthernet1/0/0.100 pop 1",
                "set interface l2 bridge GigabitEthernet1/0/0.101 10 1",
                "set interface l2 tag-rewrite GigabitEthernet1/0/0.101 pop 1",
                "set interface l2 bridge GigabitEthernet1/0/0.102 10 1",
                "set interface l2 tag-rewrite GigabitEthernet1/0/0.102 pop 1",
            ],
        )

    def test_members_in_their_group_need_nothing(self):
        cli = self.sync(CONFIG, [bridge(10, [(1, 0), (2, 1), (3, 1)])])
        self.assertEqual(cli, [])

    def test_a_member_in_another_group_is_set_again(self):
        cli = self.sync(CONFIG, [bridge(10, [(1, 0), (2, 2), (3, 1)])])
        self.assertEqual(
            cli,
            [
                "set interface l2 bridge GigabitEthernet1/0/0.101 10 1",
                "set interface l2 tag-rewrite GigabitEthernet1/0/0.101 pop 1",
            ],
        )

    def test_a_member_leaving_its_group_goes_back_to_zero(self):
        cli = self.sync(CONFIG, [bridge(10, [(1, 3), (2, 1), (3, 1)])])
        self.assertEqual(
            cli,
            [
                "set interface l2 bridge GigabitEthernet1/0/0.100 10",
                "set interface l2 tag-rewrite GigabitEthernet1/0/0.100 pop 1",
            ],
        )

    def test_a_bridge_without_groups_is_unchanged(self):
        cfg = {
            "interfaces": CONFIG["interfaces"],
            "bridgedomains": {
                "bd10": {"interfaces": ["GigabitEthernet1/0/0.100"]},
            },
        }
        self.assertEqual(self.sync(cfg, [bridge(10, [(1, 0)])]), [])


class TestDumperSplitHorizon(unittest.TestCase):
    def dump(self, bridges):
        dumper = Dumper()
        fill_cache(dumper, bridges)
        return dumper.cache_to_config()["bridgedomains"]

    def test_groups_are_dumped(self):
        bridges = self.dump([bridge(10, [(1, 0), (2, 1), (3, 1)])])
        self.assertEqual(
            bridges["bd10"]["split-horizon"],
            {"GigabitEthernet1/0/0.101": 1, "GigabitEthernet1/0/0.102": 1},
        )

    def test_no_groups_no_key(self):
        bridges = self.dump([bridge(10, [(1, 0), (2, 0)])])
        self.assertNotIn("split-horizon", bridges["bd10"])
