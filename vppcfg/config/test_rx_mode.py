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
"""Unit tests for rx-mode"""

import unittest
import yaml
from . import interface
from .unittestyaml import UnitTestYaml


class TestRxModeMethods(unittest.TestCase):
    def setUp(self):
        with UnitTestYaml("test_rx_mode.yaml") as f:
            self.cfg = yaml.load(f, Loader=yaml.FullLoader)

    def test_has_rx_queues(self):
        self.assertTrue(interface.has_rx_queues(self.cfg, "GigabitEthernet1/0/0"))
        self.assertTrue(interface.has_rx_queues(self.cfg, "tap100"))
        self.assertFalse(interface.has_rx_queues(self.cfg, "BondEthernet0"))
        self.assertFalse(interface.has_rx_queues(self.cfg, "loop0"))

    def test_get_rx_mode(self):
        ## The default, on a PHY and the TAP of its LCP
        self.assertEqual(
            interface.get_rx_mode(self.cfg, "GigabitEthernet1/0/0"), "interrupt"
        )
        ## Its own mode wins over the default
        self.assertEqual(
            interface.get_rx_mode(self.cfg, "GigabitEthernet1/0/1"), "polling"
        )
        self.assertEqual(interface.get_rx_mode(self.cfg, "loop2"), "adaptive")
        ## A bond member, a TAP, and the LCPs of a bond and a loopback
        self.assertEqual(
            interface.get_rx_mode(self.cfg, "GigabitEthernet1/0/2"), "interrupt"
        )
        self.assertEqual(interface.get_rx_mode(self.cfg, "tap100"), "interrupt")
        self.assertEqual(interface.get_rx_mode(self.cfg, "BondEthernet0"), "interrupt")
        self.assertEqual(interface.get_rx_mode(self.cfg, "loop0"), "interrupt")
        ## Nothing to set it on
        self.assertIsNone(interface.get_rx_mode(self.cfg, "GigabitEthernet1/0/0.100"))
        self.assertIsNone(interface.get_rx_mode(self.cfg, "BondEthernet1"))
        self.assertIsNone(interface.get_rx_mode(self.cfg, "loop1"))
        self.assertIsNone(interface.get_rx_mode(self.cfg, "notexist"))

    def test_no_default(self):
        del self.cfg["defaults"]
        self.assertIsNone(interface.get_rx_mode(self.cfg, "GigabitEthernet1/0/0"))
        self.assertEqual(
            interface.get_rx_mode(self.cfg, "GigabitEthernet1/0/1"), "polling"
        )
