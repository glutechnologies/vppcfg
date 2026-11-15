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
"""Unit tests for the L2 VLAN tag rewrites of the planner and the dumper, against a
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
from . import l2rewrite

SUBS = "GigabitEthernet1/0/0"
TCI_801_PCP5 = (5 << 13) | 801


def vpp_iface(idx, name, tags, vtr=(0, 0, 0, 0)):
    """An interface read from VPP, with sub_number_of_tags `tags` and the VLAN tag
    rewrite (vtr_op, vtr_push_dot1q, vtr_tag1, vtr_tag2) `vtr`."""
    return SimpleNamespace(
        sw_if_index=idx,
        sup_sw_if_index=0,
        interface_name=name,
        tag="",
        sub_id=int(name.split(".")[1]) if "." in name else 0,
        sub_number_of_tags=tags,
        vtr_op=vtr[0],
        vtr_push_dot1q=vtr[1],
        vtr_tag1=vtr[2],
        vtr_tag2=vtr[3],
    )


def fill_cache(vpp, ifaces):
    """Put the interfaces `ifaces` in the cache of vpp."""
    for iface in ifaces:
        vpp.cache["interfaces"][iface.sw_if_index] = iface
        vpp.cache["interface_names"][iface.interface_name] = iface.sw_if_index
    vpp.cache_read = True


def config(rewrites):
    """GigabitEthernet1/0/0 with .100 (dot1q) and .200 (QinAD 200.300) in bd10, and
    .101 an L2XC source to GigabitEthernet1/0/1, with the l2-rewrite {subid: rewrite}
    `rewrites`; key 0 is the l2-rewrite of the untagged GigabitEthernet1/0/1, made an
    L2XC source back to .101 when it has one."""
    subs = {
        100: {"encapsulation": {"dot1q": 100}},
        101: {"encapsulation": {"dot1q": 101}, "l2xc": "GigabitEthernet1/0/1"},
        200: {"encapsulation": {"dot1ad": 200, "inner-dot1q": 300}},
    }
    other = {}
    for subid, rewrite in rewrites.items():
        if subid == 0:
            other = {"l2xc": f"{SUBS}.101", "l2-rewrite": rewrite}
        else:
            subs[subid]["l2-rewrite"] = rewrite
    return {
        "interfaces": {SUBS: {"sub-interfaces": subs}, "GigabitEthernet1/0/1": other},
        "bridgedomains": {"bd10": {"interfaces": [f"{SUBS}.100", f"{SUBS}.200"]}},
    }


POPPED = [
    vpp_iface(0, SUBS, 0),
    vpp_iface(1, f"{SUBS}.100", 1, (3, 0, 0, 0)),
    vpp_iface(2, f"{SUBS}.101", 1, (3, 0, 0, 0)),
    vpp_iface(3, f"{SUBS}.200", 2, (4, 0, 0, 0)),
    vpp_iface(4, "GigabitEthernet1/0/1", 0),
]


class TestL2RewriteVtr(unittest.TestCase):
    def test_round_trip(self):
        rewrites = [
            {"pop": 0, "push": []},
            {"pop": 1, "push": []},
            {"pop": 2, "push": []},
            {"pop": 0, "push": [("dot1q", 5)]},
            {"pop": 0, "push": [("dot1ad", 820), ("dot1q", 821)]},
            {"pop": 1, "push": [("dot1q", TCI_801_PCP5)]},
            {"pop": 1, "push": [("dot1ad", 810), ("dot1q", 811)]},
            {"pop": 2, "push": [("dot1q", 830)]},
            {"pop": 2, "push": [("dot1ad", 900), ("dot1q", 901)]},
        ]
        for rewrite in rewrites:
            self.assertEqual(l2rewrite.from_vtr(l2rewrite.to_vtr(rewrite)), rewrite)

    def test_vtr_as_vpp_reads_it_back(self):
        ## As VPP 25.10 reported them after the CLI statements below.
        self.assertEqual(
            l2rewrite.to_vtr({"pop": 1, "push": [("dot1q", 800)]}), (5, 1, 800, 0)
        )
        self.assertEqual(
            l2rewrite.to_vtr({"pop": 2, "push": [("dot1ad", 803)]}), (7, 0, 803, 0)
        )
        self.assertEqual(l2rewrite.to_vtr({"pop": 2, "push": []}), (4, 0, 0, 0))
        self.assertIsNone(l2rewrite.from_vtr((9, 0, 0, 0)))

    def test_cli(self):
        cases = [
            ({"pop": 0, "push": []}, "disable"),
            ({"pop": 1, "push": []}, "pop 1"),
            ({"pop": 0, "push": [("dot1q", 5)]}, "push dot1q 5"),
            (
                {"pop": 0, "push": [("dot1ad", 820), ("dot1q", 821)]},
                "push dot1ad 820 821",
            ),
            (
                {"pop": 1, "push": [("dot1q", TCI_801_PCP5)]},
                f"translate 1-1 dot1q {TCI_801_PCP5}",
            ),
            (
                {"pop": 1, "push": [("dot1q", 870), ("dot1q", 871)]},
                "translate 1-2 dot1q 870 871",
            ),
            ({"pop": 2, "push": [("dot1ad", 803)]}, "translate 2-1 dot1ad 803"),
            (
                {"pop": 2, "push": [("dot1ad", 900), ("dot1q", 901)]},
                "translate 2-2 dot1ad 900 901",
            ),
        ]
        for rewrite, words in cases:
            self.assertEqual(
                l2rewrite.cli("Gi1.100", rewrite),
                f"set interface l2 tag-rewrite Gi1.100 {words}",
            )

    def test_to_config(self):
        self.assertEqual(l2rewrite.to_config({"pop": 0, "push": []}), {"pop": 0})
        self.assertEqual(
            l2rewrite.to_config(
                {
                    "pop": 1,
                    "push": [
                        ("dot1ad", (5 << 13) | (1 << 12) | 900),
                        ("dot1q", (3 << 13) | 901),
                    ],
                }
            ),
            {
                "pop": 1,
                "push": {
                    "dot1ad": 900,
                    "pcp": 5,
                    "dei": True,
                    "inner-dot1q": 901,
                    "inner-pcp": 3,
                },
            },
        )


class TestPlannerL2RewriteSync(unittest.TestCase):
    def sync(self, cfg, ifaces, prune=()):
        planner = Planner(cfg)
        fill_cache(planner.vpp, ifaces)
        planner.cli["prune"] = list(prune)
        self.assertTrue(planner._sync_l2_rewrites())
        return planner.cli["sync"]

    def test_defaults_in_place(self):
        self.assertEqual(self.sync(config({}), POPPED), [])

    def test_new_interfaces_get_the_default(self):
        ifaces = [POPPED[0], POPPED[4]]
        self.assertEqual(
            sorted(self.sync(config({}), ifaces)),
            [
                f"set interface l2 tag-rewrite {SUBS}.100 pop 1",
                f"set interface l2 tag-rewrite {SUBS}.101 pop 1",
                f"set interface l2 tag-rewrite {SUBS}.200 pop 2",
            ],
        )

    def test_translate(self):
        cfg = config(
            {
                100: {"pop": 1, "push": {"dot1q": 801, "pcp": 5}},
                200: {"pop": 2, "push": {"dot1ad": 900, "inner-dot1q": 901}},
            }
        )
        self.assertEqual(
            self.sync(cfg, POPPED),
            [
                f"set interface l2 tag-rewrite {SUBS}.100 translate 1-1 dot1q {TCI_801_PCP5}",
                f"set interface l2 tag-rewrite {SUBS}.200 translate 2-2 dot1ad 900 901",
            ],
        )

    def test_translate_in_place(self):
        cfg = config({100: {"pop": 1, "push": {"dot1q": 801, "pcp": 5}}})
        ifaces = list(POPPED)
        ifaces[1] = vpp_iface(1, f"{SUBS}.100", 1, (5, 1, TCI_801_PCP5, 0))
        self.assertEqual(self.sync(cfg, ifaces), [])

    def test_back_to_the_default(self):
        ifaces = list(POPPED)
        ifaces[1] = vpp_iface(1, f"{SUBS}.100", 1, (5, 1, TCI_801_PCP5, 0))
        self.assertEqual(
            self.sync(config({}), ifaces),
            [f"set interface l2 tag-rewrite {SUBS}.100 pop 1"],
        )

    def test_empty_rewrite_disables(self):
        self.assertEqual(
            self.sync(config({100: {}}), POPPED),
            [f"set interface l2 tag-rewrite {SUBS}.100 disable"],
        )

    def test_push_on_an_untagged_l2xc_source(self):
        cfg = config({0: {"push": {"dot1q": 1000, "inner-dot1q": 1001}}})
        self.assertEqual(
            self.sync(cfg, POPPED),
            ["set interface l2 tag-rewrite GigabitEthernet1/0/1 push dot1q 1000 1001"],
        )

    def test_reset_by_the_prune(self):
        ## The prune of a removed bridge-domain or L2XC disables the rewrite, which the
        ## cache still shows: the sync sets it again.
        prune = [
            f"set interface l2 tag-rewrite {SUBS}.101 disable",
            f"set interface l3 {SUBS}.101",
        ]
        self.assertEqual(
            self.sync(config({}), POPPED, prune),
            [f"set interface l2 tag-rewrite {SUBS}.101 pop 1"],
        )

    def test_set_again_on_a_new_join(self):
        ## A source cross-connected again, because the other end was created again,
        ## gets its rewrite again, whatever the cache said before the plan.
        sync = [
            f"set interface l2 xconnect {SUBS}.101 GigabitEthernet1/0/1",
            f"set interface l2 bridge {SUBS}.100 10",
        ]
        planner = Planner(config({}))
        fill_cache(planner.vpp, POPPED)
        planner.cli["sync"] = list(sync)
        self.assertTrue(planner._sync_l2_rewrites())
        self.assertEqual(
            planner.cli["sync"][len(sync) :],
            [
                f"set interface l2 tag-rewrite {SUBS}.100 pop 1",
                f"set interface l2 tag-rewrite {SUBS}.101 pop 1",
            ],
        )

    def test_sync_order(self):
        ## A new member joins its bridge-domain before its tags are rewritten.
        planner = Planner(config({}))
        fill_cache(planner.vpp, [POPPED[0], POPPED[1], POPPED[4]])
        planner._sync_l2xcs()
        planner._sync_l2_rewrites()
        self.assertEqual(
            planner.cli["sync"],
            [
                f"set interface l2 xconnect {SUBS}.101 GigabitEthernet1/0/1",
                f"set interface l2 tag-rewrite {SUBS}.101 pop 1",
                f"set interface l2 tag-rewrite {SUBS}.200 pop 2",
            ],
        )


class TestDumperL2Rewrite(unittest.TestCase):
    def dump(self, ifaces, members=(), l2xcs=()):
        dumper = Dumper()
        fill_cache(dumper, ifaces)
        dumper.cache["bridgedomains"][10] = SimpleNamespace(
            bvi_sw_if_index=2**32 - 1,
            sw_if_details=[SimpleNamespace(sw_if_index=idx) for idx in members],
        )
        for idx in l2xcs:
            dumper.cache["l2xcs"][idx] = SimpleNamespace(rx_sw_if_index=idx)
        ret = {}
        for iface in ifaces:
            config_iface = {}
            dumper._l2_rewrite_to_config(iface, config_iface)
            if config_iface:
                ret[iface.interface_name] = config_iface["l2-rewrite"]
        return ret

    def test_defaults_are_not_exported(self):
        self.assertEqual(self.dump(POPPED, members=(1, 3), l2xcs=(2,)), {})

    def test_other_rewrites_are_exported(self):
        ifaces = list(POPPED)
        ifaces[1] = vpp_iface(1, f"{SUBS}.100", 1, (5, 1, TCI_801_PCP5, 0))
        ifaces[3] = vpp_iface(3, f"{SUBS}.200", 2, (0, 0, 0, 0))
        ifaces[4] = vpp_iface(4, "GigabitEthernet1/0/1", 0, (1, 0, 1000, 0))
        self.assertEqual(
            self.dump(ifaces, members=(1, 3), l2xcs=(2, 4)),
            {
                f"{SUBS}.100": {"pop": 1, "push": {"dot1q": 801, "pcp": 5}},
                f"{SUBS}.200": {"pop": 0},
                "GigabitEthernet1/0/1": {"pop": 0, "push": {"dot1ad": 1000}},
            },
        )

    def test_rewrite_outside_l2(self):
        ## Not a bridge-domain member nor an L2XC source: the default is no rewrite.
        self.assertEqual(
            self.dump(POPPED, members=(1,), l2xcs=()),
            {f"{SUBS}.101": {"pop": 1}, f"{SUBS}.200": {"pop": 2}},
        )


if __name__ == "__main__":
    unittest.main()
