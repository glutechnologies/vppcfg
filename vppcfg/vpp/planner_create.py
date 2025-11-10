# Copyright (c) 2025 Pim van Pelt
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
"""
Planner create operations - handles creation of objects in VPP that exist in config but not in VPP.
"""

from vppcfg.config import loopback
from vppcfg.config import interface
from vppcfg.config import bondethernet
from vppcfg.config import bridgedomain
from vppcfg.config import vxlan_tunnel
from vppcfg.config import tap
from .planner_base import PlannerBase


class PlannerCreateOperations(PlannerBase):  # pylint: disable=too-few-public-methods
    """Mixin class providing create operations for the Planner."""

    def create(self):
        """Create all objects in VPP that occur in the config but not in VPP. For an indepth
        explanation of how and why this particular creation order is chosen, see README.md
        section on Planning."""
        ret = True
        if not self._create_loopbacks():
            self.logger.warning("Could not create Loopbacks in VPP")
            ret = False
        if not self._create_bondethernets():
            self.logger.warning("Could not create BondEthernets in VPP")
            ret = False
        if not self._create_vxlan_tunnels():
            self.logger.warning("Could not create VXLAN Tunnels in VPP")
            ret = False
        if not self._create_taps():
            self.logger.warning("Could not create TAPs in VPP")
            ret = False
        if not self._create_sub_interfaces():
            self.logger.warning("Could not create Sub Interfaces in VPP")
            ret = False
        if not self._create_bridgedomains():
            self.logger.warning("Could not create BridgeDomains in VPP")
            ret = False
        if not self._create_lcps():
            self.logger.warning("Could not create LCPs in VPP")
            ret = False
        return ret

    def _create_loopbacks(self):
        """Create all loopbacks that occur in the config but not in VPP"""
        for ifname in loopback.get_loopbacks(self.cfg):
            if ifname in self.vpp.cache["interface_names"]:
                continue
            instance = int(ifname[4:])
            cli = f"create loopback interface instance {int(instance)}"
            ifname, iface = loopback.get_by_name(self.cfg, ifname)
            if "mac" in iface:
                cli += f" mac {iface['mac']}"
            self.cli["create"].append(cli)
        return True

    def _create_bondethernets(self):
        """Create all bondethernets that occur in the config but not in VPP"""
        for ifname in bondethernet.get_bondethernets(self.cfg):
            if ifname in self.vpp.cache["interface_names"]:
                continue
            ifname, iface = bondethernet.get_by_name(self.cfg, ifname)
            instance = int(ifname[12:])
            mode = bondethernet.get_mode(self.cfg, ifname)
            cli = f"create bond id {int(instance)} mode {mode}"
            loadbalance = bondethernet.get_lb(self.cfg, ifname)
            if loadbalance:
                cli += f" load-balance {loadbalance}"
            if "mac" in iface:
                cli += f" hw-addr {iface['mac']}"
            self.cli["create"].append(cli)
        return True

    def _create_vxlan_tunnels(self):
        """Create all vxlan_tunnels that occur in the config but not in VPP"""
        for ifname in vxlan_tunnel.get_vxlan_tunnels(self.cfg):
            if ifname in self.vpp.cache["interface_names"]:
                continue
            ifname, iface = vxlan_tunnel.get_by_name(self.cfg, ifname)
            instance = int(ifname[12:])
            cli = (
                f"create vxlan tunnel src {iface['local']} dst {iface['remote']} "
                f"instance {instance} vni {iface['vni']} decap-next l2"
            )
            self.cli["create"].append(cli)
        return True

    def _create_sub_interfaces(self):
        """Create all sub-interfaces that occur in the config but not in VPP"""
        ## First create 1-tag (Dot1Q/Dot1AD), and then create 2-tag (Qin*) sub-interfaces
        for do_qinx in [False, True]:
            for ifname in interface.get_sub_interfaces(self.cfg):
                if not do_qinx == interface.is_qinx(self.cfg, ifname):
                    continue

                ifname, _iface = interface.get_by_name(self.cfg, ifname)
                if ifname in self.vpp.cache["interface_names"]:
                    continue

                ## Assemble the encapsulation string
                encap = interface.get_encapsulation(self.cfg, ifname)
                if encap["dot1ad"] > 0:
                    encapstr = f"dot1ad {int(encap['dot1ad'])}"
                else:
                    encapstr = f"dot1q {int(encap['dot1q'])}"
                if do_qinx:
                    encapstr += f" inner-dot1q {int(encap['inner-dot1q'])}"
                if encap["exact-match"]:
                    encapstr += " exact-match"
                parent, subid = ifname.split(".")
                cli = f"create sub {parent} {int(int(subid))} {encapstr}"
                self.cli["create"].append(cli)
        return True

    def _create_taps(self):
        """Create all taps that occur in the config but not in VPP"""
        for ifname in tap.get_taps(self.cfg):
            ifname, iface = tap.get_by_name(self.cfg, ifname)
            if ifname in self.vpp.cache["interface_names"]:
                continue
            instance = int(ifname[3:])
            cli = f"create tap id {int(instance)} host-if-name {iface['host']['name']}"
            if "mac" in iface["host"]:
                cli += f" host-mac-addr {iface['host']['mac']}"
            if "namespace" in iface["host"]:
                cli += f" host-ns {int(iface['host']['namespace'])}"
            if "bridge" in iface["host"]:
                cli += f" host-bridge {iface['host']['bridge']}"
            if "mtu" in iface["host"]:
                cli += f" host-mtu-size {int(iface['host']['mtu'])}"
            if "rx-ring-size" in iface:
                cli += f" rx-ring-size {int(iface['rx-ring-size'])}"
            if "tx-ring-size" in iface:
                cli += f" tx-ring-size {int(iface['tx-ring-size'])}"
            self.cli["create"].append(cli)

        return True

    def _create_bridgedomains(self):
        """Create all bridgedomains that occur in the config but not in VPP"""
        for ifname in bridgedomain.get_bridgedomains(self.cfg):
            ifname, _iface = bridgedomain.get_by_name(self.cfg, ifname)
            instance = int(ifname[2:])
            settings = bridgedomain.get_settings(self.cfg, ifname)
            if instance in self.vpp.cache["bridgedomains"]:
                continue
            cli = f"create bridge-domain {instance}"
            if not settings["learn"]:
                cli += " learn 0"
            if not settings["unicast-flood"]:
                cli += " flood 0"
            if not settings["unknown-unicast-flood"]:
                cli += " uu-flood 0"
            if not settings["unicast-forward"]:
                cli += " forward 0"
            if settings["arp-termination"]:
                cli += " arp-term 1"
            if settings["arp-unicast-forward"]:
                cli += " arp-ufwd 1"
            if settings["mac-age-minutes"] > 0:
                cli += f" mac-age {int(settings['mac-age-minutes'])}"
            self.cli["create"].append(cli)
        return True

    def _create_lcps(self):
        """Create all LCPs that occur in the config but not in VPP"""
        lcpnames = [
            self.vpp.cache["lcps"][x].host_if_name for x in self.vpp.cache["lcps"]
        ]

        ## First create untagged ...
        for ifname in loopback.get_loopbacks(self.cfg) + interface.get_interfaces(
            self.cfg
        ):
            if interface.is_sub(self.cfg, ifname):
                continue

            if ifname.startswith("loop"):
                ifname, iface = loopback.get_by_name(self.cfg, ifname)
            else:
                ifname, iface = interface.get_by_name(self.cfg, ifname)
            if not "lcp" in iface:
                continue
            if iface["lcp"] in lcpnames:
                continue
            cli = f"lcp create {ifname} host-if {iface['lcp']}"
            self.cli["create"].append(cli)

        ## ... then 1-tag (Dot1Q/Dot1AD), and then create 2-tag (Qin*) LCPs
        for do_qinx in [False, True]:
            for ifname in interface.get_sub_interfaces(self.cfg):
                if not do_qinx == interface.is_qinx(self.cfg, ifname):
                    continue
                ifname, iface = interface.get_by_name(self.cfg, ifname)
                if not "lcp" in iface:
                    continue
                if iface["lcp"] in lcpnames:
                    continue
                cli = f"lcp create {ifname} host-if {iface['lcp']}"
                self.cli["create"].append(cli)
        return True
