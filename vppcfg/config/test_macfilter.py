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
"""Unit tests for MAC filters"""

import unittest
import yaml
from . import macfilter
from .unittestyaml import UnitTestYaml


class TestMacFilterMethods(unittest.TestCase):
    def setUp(self):
        with UnitTestYaml("test_macfilter.yaml") as f:
            self.cfg = yaml.load(f, Loader=yaml.FullLoader)

    def test_get_mac_filters(self):
        self.assertEqual(
            sorted(macfilter.get_mac_filters(self.cfg)),
            ["no-pairs", "nothing", "only-the-router"],
        )
        self.assertEqual(macfilter.get_mac_filters({}), [])

    def test_get_by_name(self):
        name, mac_filter = macfilter.get_by_name(self.cfg, "nothing")
        self.assertEqual(name, "nothing")
        self.assertEqual(mac_filter["miss"], "deny")
        self.assertEqual(macfilter.get_by_name(self.cfg, "absent"), (None, None))
        self.assertEqual(macfilter.get_by_name({}, "nothing"), (None, None))

    def test_get_mask(self):
        ## In the order of the Ethernet header, whatever the order in the config.
        _name, mac_filter = macfilter.get_by_name(self.cfg, "no-pairs")
        self.assertEqual(macfilter.get_mask(mac_filter), ["dst", "src"])

    def test_get_entries(self):
        _name, mac_filter = macfilter.get_by_name(self.cfg, "only-the-router")
        self.assertEqual(macfilter.get_entries(mac_filter), {("74:4d:28:80:df:d6",)})
        _name, mac_filter = macfilter.get_by_name(self.cfg, "no-pairs")
        self.assertEqual(
            macfilter.get_entries(mac_filter),
            {("02:00:00:00:00:02", "02:00:00:00:00:01")},
        )
        _name, mac_filter = macfilter.get_by_name(self.cfg, "nothing")
        self.assertEqual(macfilter.get_entries(mac_filter), set())

    def test_interfaces(self):
        self.assertEqual(
            macfilter.get_interface_mac_filter(self.cfg, "GigabitEthernet1/0/0.100"),
            "only-the-router",
        )
        self.assertIsNone(
            macfilter.get_interface_mac_filter(self.cfg, "GigabitEthernet1/0/0.102")
        )
        self.assertIsNone(
            macfilter.get_interface_mac_filter(self.cfg, "GigabitEthernet9/0/0")
        )
        self.assertEqual(
            macfilter.get_mac_filter_interfaces(self.cfg),
            ["GigabitEthernet1/0/0.100", "GigabitEthernet1/0/0.101"],
        )
