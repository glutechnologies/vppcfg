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
"""Unit tests for the MAC filters of the planner, the dumper and the applier, against
a VPP configuration cache filled by hand instead of read from a running VPP."""

import copy
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
from .applier import Applier
from . import macfilter

ANY = 2**32 - 1
ROUTER = "74:4d:28:80:df:d6"
OTHER = "02:00:00:00:00:01"


def table(mask, miss, hits, match_n_vectors=1):
    """A classify table read from VPP: info and sessions, the latter one per
    (mask values, hit) in hits."""
    return {
        "info": SimpleNamespace(
            skip_n_vectors=0,
            match_n_vectors=match_n_vectors,
            next_table_index=ANY,
            miss_next_index=macfilter.NEXT_INDEX[miss],
            mask=macfilter.mask_bytes(mask),
        ),
        "sessions": [
            SimpleNamespace(
                ## VPP keeps the hit next index in 16 bits: ~0 reads back as 0xffff.
                hit_next_index=macfilter.NEXT_INDEX[hit] & 0xFFFF,
                match=macfilter.match_bytes(mask, values),
            )
            for values, hit in hits
        ],
    }


def fill_cache(vpp, tables, bound):
    """Interfaces 1-3 are GigabitEthernet1/0/0.100-102, with the given classify tables
    {index: table} and L2 output ACL tables {sw_if_index: index}."""
    vpp.cache["interfaces"][0] = SimpleNamespace(
        sw_if_index=0,
        sup_sw_if_index=0,
        interface_name="GigabitEthernet1/0/0",
        tag="",
        sub_id=0,
        sub_number_of_tags=0,
    )
    vpp.cache["interface_names"]["GigabitEthernet1/0/0"] = 0
    for idx in (1, 2, 3):
        name = f"GigabitEthernet1/0/0.{99 + idx}"
        vpp.cache["interfaces"][idx] = SimpleNamespace(
            sw_if_index=idx,
            sup_sw_if_index=0,
            interface_name=name,
            tag="",
            sub_id=99 + idx,
            sub_number_of_tags=1,
        )
        vpp.cache["interface_names"][name] = idx
    vpp.cache["classify_tables"] = copy.deepcopy(tables)
    vpp.cache["interface_l2_output_tables"] = dict(bound)
    vpp.cache_read = True


SUBS = "GigabitEthernet1/0/0"


def config(filters, outputs):
    """A config with sub-interfaces .100-.102 in bd10, the MAC filters `filters` and the
    mac-filter-output {subid: filter name} `outputs`."""
    subs = {}
    for subid in (100, 101, 102):
        subs[subid] = {"encapsulation": {"dot1q": subid}}
        if subid in outputs:
            subs[subid]["mac-filter-output"] = outputs[subid]
    return {
        "interfaces": {SUBS: {"sub-interfaces": subs}},
        "bridgedomains": {
            "bd10": {"interfaces": [f"{SUBS}.{subid}" for subid in (100, 101, 102)]}
        },
        "mac-filters": filters,
    }


ROUTER_ONLY = {"mask": ["src"], "miss": "deny", "entries": [{"src": ROUTER}]}


class TestPlannerMacFilterSync(unittest.TestCase):
    def sync(self, cfg, tables, bound):
        planner = Planner(cfg)
        fill_cache(planner.vpp, tables, bound)
        self.assertTrue(planner._sync_mac_filters())
        return planner.cli["sync"]

    def test_new_filter(self):
        cli = self.sync(config({"vex0": ROUTER_ONLY}, {101: "vex0"}), {}, {})
        self.assertEqual(
            cli,
            [
                "classify table acl-miss-next deny mask l2 src",
                f"classify session acl-hit-next permit table-index $new-table match l2 src {ROUTER}",
                f"set interface output acl intfc {SUBS}.101 l2-table $new-table",
            ],
        )

    def test_both_fields_in_header_order(self):
        cfg = config(
            {
                "pair": {
                    "mask": ["src", "dst"],
                    "miss": "permit",
                    "entries": [{"src": ROUTER, "dst": OTHER}],
                }
            },
            {100: "pair"},
        )
        cli = self.sync(cfg, {}, {})
        self.assertEqual(
            cli,
            [
                "classify table acl-miss-next permit mask l2 dst src",
                f"classify session acl-hit-next deny table-index $new-table match l2 dst {OTHER} src {ROUTER}",
                f"set interface output acl intfc {SUBS}.100 l2-table $new-table",
            ],
        )

    def test_same_filter_needs_nothing(self):
        tables = {4: table(["src"], "deny", [((ROUTER,), "permit")])}
        cfg = config({"vex0": ROUTER_ONLY}, {101: "vex0"})
        self.assertEqual(self.sync(cfg, tables, {2: 4}), [])

    def test_entries_change_in_place(self):
        tables = {4: table(["src"], "deny", [((OTHER,), "permit")])}
        cfg = config({"vex0": ROUTER_ONLY}, {101: "vex0"})
        self.assertEqual(
            self.sync(cfg, tables, {2: 4}),
            [
                f"classify session acl-hit-next permit table-index 4 match l2 src {ROUTER}",
                f"classify session del table-index 4 match l2 src {OTHER}",
            ],
        )

    def test_other_miss_replaces_the_table(self):
        tables = {4: table(["src"], "permit", [((ROUTER,), "deny")])}
        cfg = config({"vex0": ROUTER_ONLY}, {101: "vex0"})
        self.assertEqual(
            self.sync(cfg, tables, {2: 4}),
            [
                "classify table acl-miss-next deny mask l2 src",
                f"classify session acl-hit-next permit table-index $new-table match l2 src {ROUTER}",
                f"set interface output acl intfc {SUBS}.101 l2-table 4 del",
                f"set interface output acl intfc {SUBS}.101 l2-table $new-table",
                "classify table del table 4",
            ],
        )

    def test_other_mask_replaces_the_table(self):
        tables = {4: table(["dst"], "deny", [((ROUTER,), "permit")])}
        cfg = config({"vex0": ROUTER_ONLY}, {101: "vex0"})
        self.assertEqual(
            self.sync(cfg, tables, {2: 4})[0],
            "classify table acl-miss-next deny mask l2 src",
        )

    def test_session_of_another_action_replaces_the_table(self):
        tables = {4: table(["src"], "deny", [((ROUTER,), "deny")])}
        cfg = config({"vex0": ROUTER_ONLY}, {101: "vex0"})
        self.assertEqual(len(self.sync(cfg, tables, {2: 4})), 5)

    def test_a_shared_table_is_replaced_and_kept(self):
        ## Each interface gets a table of its own; the one it shared stays for the other.
        tables = {4: table(["src"], "deny", [((ROUTER,), "permit")])}
        cfg = config({"vex0": ROUTER_ONLY}, {101: "vex0", 102: "vex0"})
        cli = self.sync(cfg, tables, {2: 4, 3: 4})
        self.assertEqual(
            cli,
            [
                "classify table acl-miss-next deny mask l2 src",
                f"classify session acl-hit-next permit table-index $new-table match l2 src {ROUTER}",
                f"set interface output acl intfc {SUBS}.101 l2-table 4 del",
                f"set interface output acl intfc {SUBS}.101 l2-table $new-table",
            ],
        )


class TestPlannerMacFilterPrune(unittest.TestCase):
    def test_filter_removed_from_config(self):
        tables = {4: table(["src"], "deny", [((ROUTER,), "permit")])}
        planner = Planner(config({}, {}))
        fill_cache(planner.vpp, tables, {2: 4})
        bindings = planner._mac_filter_bindings()
        planner.cli["prune"] = ["delete sub GigabitEthernet9/0/0.100"]
        self.assertTrue(planner._prune_mac_filters(bindings))
        self.assertEqual(
            planner.cli["prune"],
            [
                f"set interface output acl intfc {SUBS}.101 l2-table 4 del",
                "classify table del table 4",
                "delete sub GigabitEthernet9/0/0.100",
            ],
        )
        self.assertEqual(planner.vpp.cache["classify_tables"], {})
        self.assertEqual(planner.vpp.cache["interface_l2_output_tables"], {})

    def test_interface_deleted_by_the_prune(self):
        ## The filter stays in the config, but its interface is deleted (and created
        ## again): VPP would keep the table on the sw_if_index, so it goes first.
        tables = {4: table(["src"], "deny", [((ROUTER,), "permit")])}
        planner = Planner(config({"vex0": ROUTER_ONLY}, {101: "vex0"}))
        fill_cache(planner.vpp, tables, {2: 4})
        bindings = planner._mac_filter_bindings()
        planner.cli["prune"] = [f"delete sub {SUBS}.101"]
        del planner.vpp.cache["interfaces"][2]
        del planner.vpp.cache["interface_names"][f"{SUBS}.101"]
        self.assertTrue(planner._prune_mac_filters(bindings))
        self.assertEqual(
            planner.cli["prune"],
            [
                f"set interface output acl intfc {SUBS}.101 l2-table 4 del",
                "classify table del table 4",
                f"delete sub {SUBS}.101",
            ],
        )

    def test_kept_filter_is_left_to_sync(self):
        tables = {4: table(["src"], "permit", [])}
        planner = Planner(config({"vex0": ROUTER_ONLY}, {101: "vex0"}))
        fill_cache(planner.vpp, tables, {2: 4})
        self.assertTrue(planner._prune_mac_filters(planner._mac_filter_bindings()))
        self.assertEqual(planner.cli["prune"], [])

    def test_shared_table_deleted_with_its_last_user(self):
        tables = {4: table(["src"], "deny", [])}
        planner = Planner(config({"vex0": ROUTER_ONLY}, {102: "vex0"}))
        fill_cache(planner.vpp, tables, {2: 4, 3: 4})
        self.assertTrue(planner._prune_mac_filters(planner._mac_filter_bindings()))
        self.assertEqual(
            planner.cli["prune"],
            [f"set interface output acl intfc {SUBS}.101 l2-table 4 del"],
        )


class TestDumperMacFilter(unittest.TestCase):
    def test_filters_are_dumped(self):
        dumper = Dumper()
        tables = {
            4: table(["src"], "deny", [((ROUTER,), "permit")]),
            5: table(["dst", "src"], "permit", [((OTHER, ROUTER), "deny")]),
            6: table(["src"], "deny", [], match_n_vectors=2),
        }
        fill_cache(dumper, tables, {1: 6, 2: 4, 3: 5})
        config = {
            "interfaces": {SUBS: {"sub-interfaces": {100: {}, 101: {}, 102: {}}}},
            "mac-filters": {},
        }
        dumper._mac_filters_to_config(config)
        self.assertEqual(
            config["mac-filters"],
            {
                "vppmacfilter4": {
                    "mask": ["src"],
                    "miss": "deny",
                    "entries": [{"src": ROUTER}],
                },
                "vppmacfilter5": {
                    "mask": ["dst", "src"],
                    "miss": "permit",
                    "entries": [{"dst": OTHER, "src": ROUTER}],
                },
            },
        )
        subs = config["interfaces"][SUBS]["sub-interfaces"]
        self.assertEqual(subs[100], {})  ## table 6 is not a MAC filter
        self.assertEqual(subs[101], {"mac-filter-output": "vppmacfilter4"})
        self.assertEqual(subs[102], {"mac-filter-output": "vppmacfilter5"})


class FakeApplier(Applier):
    """An Applier whose VPP creates a classify table at index 7 for each statement
    that creates one, and records the statements it runs."""

    def __init__(self, cli):  # pylint: disable=super-init-not-called
        self.logger = SimpleNamespace(
            debug=lambda *_: None,
            info=lambda *_: None,
            warning=lambda *_: None,
            error=lambda *_: None,
        )
        self.cli = cli
        self.ran = []
        self.tables = {1, 2}

    def cli_inband(self, cmd):
        self.ran.append(cmd)
        if self.creates_classify_table(cmd):
            self.tables.add(7)
        return SimpleNamespace(retval=0, reply="")

    def classify_table_ids(self):
        return set(self.tables)


class TestApplierNewTable(unittest.TestCase):
    def test_new_table_is_resolved(self):
        cli = {
            "prune": [],
            "create": [],
            "sync": [
                "classify table acl-miss-next deny mask l2 src",
                f"classify session acl-hit-next permit table-index $new-table match l2 src {ROUTER}",
                f"set interface output acl intfc {SUBS}.101 l2-table 4 del",
                f"set interface output acl intfc {SUBS}.101 l2-table $new-table",
                "classify table del table 4",
            ],
        }
        applier = FakeApplier(cli)
        self.assertTrue(applier.apply())
        self.assertEqual(
            applier.ran,
            [
                "classify table acl-miss-next deny mask l2 src",
                f"classify session acl-hit-next permit table-index 7 match l2 src {ROUTER}",
                f"set interface output acl intfc {SUBS}.101 l2-table 4 del",
                f"set interface output acl intfc {SUBS}.101 l2-table 7",
                "classify table del table 4",
            ],
        )

    def test_without_a_new_table_it_fails(self):
        cli = {
            "prune": [],
            "create": [],
            "sync": [f"set interface output acl intfc {SUBS}.101 l2-table $new-table"],
        }
        applier = FakeApplier(cli)
        self.assertFalse(applier.apply())
        self.assertEqual(applier.ran, [])

    def test_creates_classify_table(self):
        self.assertTrue(
            Applier.creates_classify_table(
                "classify table acl-miss-next deny mask l2 src"
            )
        )
        self.assertFalse(Applier.creates_classify_table("classify table del table 4"))
        self.assertFalse(
            Applier.creates_classify_table("classify table table 4 next-table 5")
        )
        self.assertFalse(
            Applier.creates_classify_table(
                "classify session del table-index 4 match l2 src 1"
            )
        )
