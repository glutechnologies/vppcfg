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
Planner prune operations - handles removal of objects from VPP that don't exist in config.
"""

from vppcfg.config import loopback
from vppcfg.config import interface
from vppcfg.config import bondethernet
from vppcfg.config import bridgedomain
from vppcfg.config import vxlan_tunnel
from vppcfg.config import tap
from .planner_base import PlannerBase


class PlannerPruneOperations(PlannerBase):  # pylint: disable=too-few-public-methods
    """Mixin class providing prune operations for the Planner."""

    def prune(self):
        """Remove all objects from VPP that do not occur in the config. For an indepth explanation
        of how and why this particular pruning order is chosen, see README.md section on
        Planning."""
        ret = True
        if not self._prune_admin_state():
            self.logger.warning("Could not set interfaces down in VPP")
            ret = False
        if not self._prune_lcps():
            self.logger.warning("Could not prune LCPs from VPP")
            ret = False
        if not self._prune_bridgedomains():
            self.logger.warning("Could not prune BridgeDomains from VPP")
            ret = False
        if not self._prune_loopbacks():
            self.logger.warning("Could not prune Loopbacks from VPP")
            ret = False
        if not self._prune_l2xcs():
            self.logger.warning("Could not prune L2 Cross Connects from VPP")
            ret = False
        if not self._prune_sub_interfaces():
            self.logger.warning("Could not prune Sub Interfaces from VPP")
            ret = False
        if not self._prune_taps():
            self.logger.warning("Could not prune TAPs from VPP")
            ret = False
        if not self._prune_vxlan_tunnels():
            self.logger.warning("Could not prune VXLAN Tunnels from VPP")
            ret = False
        if not self._prune_bondethernets():
            self.logger.warning("Could not prune BondEthernets from VPP")
            ret = False
        if not self._prune_phys():
            self.logger.warning("Could not prune PHYs from VPP")
            ret = False
        return ret

    def _prune_unnumbered_usage(self, target_ifname):
        """Remove the unnumbered use of all VPP interfaces that are using the given 'target_ifname'."""
        target_iface = self.vpp.get_interface_by_name(target_ifname)

        for idx, target_idx in self.vpp.cache["interface_unnumbered"].items():
            if target_idx == target_iface.sw_if_index:
                unnumbered_ifname = self.vpp.cache["interfaces"][idx].interface_name
                cli = f"set interface unnumbered del {unnumbered_ifname}"
                self.cli["prune"].append(cli)
        return True

    def _prune_addresses(self, ifname, address_list):
        """Remove all addresses from interface ifname, except those in address_list,
        which may be an empty list, in which case all addresses are removed.
        """
        _iface = self.vpp.get_interface_by_name(ifname)
        if not _iface:
            self.logger.error(
                f"Trying to prune addresses from non-existent interface {ifname}"
            )
            return

        idx = _iface.sw_if_index
        removed_addresses = []
        for addr in self.vpp.cache["interface_addresses"][idx]:
            if not addr in address_list:
                cli = f"set interface ip address del {ifname} {addr}"
                self.cli["prune"].append(cli)
                removed_addresses.append(addr)
            else:
                self.logger.debug(f"Address OK: {ifname} {addr}")
        for addr in removed_addresses:
            self.vpp.cache["interface_addresses"][idx].remove(addr)

    def _prune_loopbacks(self):
        """Remove loopbacks from VPP, if they do not occur in the config."""
        removed_interfaces = []
        for numtags in [2, 1, 0]:
            for _idx, vpp_iface in self.vpp.cache["interfaces"].items():
                if vpp_iface.interface_dev_type != "Loopback":
                    continue
                if vpp_iface.sub_number_of_tags != numtags:
                    continue
                if self.vpp.is_foreign_interface(vpp_iface.sw_if_index):
                    ## Owned by an external controlplane, leave it alone.
                    continue
                _config_ifname, config_iface = loopback.get_by_name(
                    self.cfg, vpp_iface.interface_name
                )
                if not config_iface:
                    self._prune_addresses(vpp_iface.interface_name, [])
                    self._prune_unnumbered_usage(vpp_iface.interface_name)
                    if numtags == 0:
                        cli = f"delete loopback interface intfc {vpp_iface.interface_name}"
                        self.cli["prune"].append(cli)
                        removed_interfaces.append(vpp_iface.interface_name)
                    else:
                        cli = f"delete sub {vpp_iface.interface_name}"
                        self.cli["prune"].append(cli)
                        removed_interfaces.append(vpp_iface.interface_name)
                    continue
                self.logger.debug(f"Loopback OK: {vpp_iface.interface_name}")
                addresses = []
                if "addresses" in config_iface:
                    addresses = config_iface["addresses"]
                self._prune_addresses(vpp_iface.interface_name, addresses)

        for ifname in removed_interfaces:
            self.vpp.cache_remove_interface(ifname)

        return True

    def _prune_bridgedomains(self):
        """Remove bridge-domains from VPP, if they do not occur in the config. If any interfaces are
        found in to-be removed bridge-domains, they are returned to L3 mode, and tag-rewrites removed.
        """
        for idx, bridge in self.vpp.cache["bridgedomains"].items():
            if self.vpp.is_foreign_bridgedomain(idx):
                ## Owned by an external controlplane, leave it alone. Bridge-domains
                ## without a tag are considered ours (VPP cannot tag them after
                ## creation), so only ones with a foreign bd_tag are skipped here.
                continue
            bridgename = f"bd{int(idx)}"
            _config_ifname, config_iface = bridgedomain.get_by_name(
                self.cfg, bridgename
            )
            if not config_iface:
                for member in bridge.sw_if_details:
                    if member.sw_if_index == bridge.bvi_sw_if_index:
                        continue
                    if self.vpp.is_foreign_interface(member.sw_if_index):
                        ## Owned by an external controlplane, never return it to L3.
                        continue
                    member_iface = self.vpp.cache["interfaces"][member.sw_if_index]
                    member_ifname = member_iface.interface_name
                    if member_iface.sub_id > 0:
                        cli = f"set interface l2 tag-rewrite {member_ifname} disable"
                        self.cli["prune"].append(cli)
                    cli = f"set interface l3 {member_ifname}"
                    self.cli["prune"].append(cli)
                if bridge.bvi_sw_if_index in self.vpp.cache["interfaces"]:
                    bviname = self.vpp.cache["interfaces"][
                        bridge.bvi_sw_if_index
                    ].interface_name
                    cli = f"set interface l3 {bviname}"
                    self.cli["prune"].append(cli)
                cli = f"create bridge-domain {int(idx)} del"
                self.cli["prune"].append(cli)
            else:
                self.logger.debug(f"BridgeDomain OK: {bridgename}")
                for member in bridge.sw_if_details:
                    if self.vpp.is_foreign_interface(member.sw_if_index):
                        ## Owned by an external controlplane, never return it to L3.
                        continue
                    member_ifname = self.vpp.cache["interfaces"][
                        member.sw_if_index
                    ].interface_name
                    if (
                        "members" in config_iface
                        and member_ifname in config_iface["members"]
                    ):
                        if interface.is_sub(self.cfg, member_ifname):
                            cli = (
                                f"set interface l2 tag-rewrite {member_ifname} disable"
                            )
                            self.cli["prune"].append(cli)
                        cli = f"set interface l3 {member_ifname}"
                        self.cli["prune"].append(cli)
                if (
                    "bvi" in config_iface
                    and bridge.bvi_sw_if_index in self.vpp.cache["interfaces"]
                ):
                    bviname = self.vpp.cache["interfaces"][
                        bridge.bvi_sw_if_index
                    ].interface_name
                    if bviname != config_iface["bvi"]:
                        cli = f"set interface l3 {bviname}"
                        self.cli["prune"].append(cli)

        return True

    def _prune_l2xcs(self):
        """Remove all L2XC source interfaces from VPP, if they do not occur in the config. If they occur,
        but are crossconnected to a different interface name, also remove them. Interfaces are put
        back into L3 mode, and their tag-rewrites removed."""
        removed_l2xcs = []
        for _idx, l2xc in self.vpp.cache["l2xcs"].items():
            if self.vpp.is_foreign_interface(l2xc.rx_sw_if_index):
                ## Owned by an external controlplane, leave it alone.
                continue
            vpp_rx_ifname = self.vpp.cache["interfaces"][
                l2xc.rx_sw_if_index
            ].interface_name
            config_rx_ifname, config_rx_iface = interface.get_by_name(
                self.cfg, vpp_rx_ifname
            )
            if not config_rx_ifname:
                if self.vpp.cache["interfaces"][l2xc.rx_sw_if_index].sub_id > 0:
                    cli = f"set interface l2 tag-rewrite {vpp_rx_ifname} disable"
                    self.cli["prune"].append(cli)
                cli = f"set interface l3 {vpp_rx_ifname}"
                self.cli["prune"].append(cli)
                removed_l2xcs.append(vpp_rx_ifname)
                continue

            if not interface.is_l2xc_interface(self.cfg, config_rx_ifname):
                if interface.is_sub(self.cfg, config_rx_ifname):
                    cli = f"set interface l2 tag-rewrite {vpp_rx_ifname} disable"
                    self.cli["prune"].append(cli)
                cli = f"set interface l3 {vpp_rx_ifname}"
                self.cli["prune"].append(cli)
                removed_l2xcs.append(vpp_rx_ifname)
                continue
            vpp_tx_ifname = self.vpp.cache["interfaces"][
                l2xc.tx_sw_if_index
            ].interface_name
            if vpp_tx_ifname != config_rx_iface["l2xc"]:
                if interface.is_sub(self.cfg, config_rx_ifname):
                    cli = f"set interface l2 tag-rewrite {vpp_rx_ifname} disable"
                    self.cli["prune"].append(cli)
                cli = f"set interface l3 {vpp_rx_ifname}"
                self.cli["prune"].append(cli)
                removed_l2xcs.append(vpp_rx_ifname)
                continue
            self.logger.debug(f"L2XC OK: {vpp_rx_ifname} -> {vpp_tx_ifname}")
        for l2xc in removed_l2xcs:
            self.vpp.cache_remove_l2xc(l2xc)
        return True

    def _vxlan_tunnel_has_diff(self, ifname):
        """Returns True if the given ifname (vxlan_tunnel0) has different attributes between VPP
        and the given configuration, or if either does not exist.

        Returns False if they are identical."""

        vpp_iface = self.vpp.get_interface_by_name(ifname)
        if (
            not vpp_iface
            or vpp_iface.sw_if_index not in self.vpp.cache["vxlan_tunnels"]
        ):
            return True
        vpp_vxlan = self.vpp.cache["vxlan_tunnels"][vpp_iface.sw_if_index]

        _config_ifname, config_iface = vxlan_tunnel.get_by_name(self.cfg, ifname)
        if not config_iface:
            return True

        if config_iface["local"] != str(vpp_vxlan.src_address):
            return True
        if config_iface["remote"] != str(vpp_vxlan.dst_address):
            return True
        if config_iface["vni"] != vpp_vxlan.vni:
            return True
        return False

    def _tap_has_diff(self, ifname):  # pylint: disable=too-many-return-statements
        """Returns True if the given ifname (tap0) has different attributes between VPP
        and the given configuration, or if either does not exist.

        Returns False if the TAP is a Linux Control Plane LIP.
        Returns False if they are identical."""

        vpp_iface = self.vpp.get_interface_by_name(ifname)
        vpp_tap = self.vpp.cache["taps"][vpp_iface.sw_if_index]
        if not vpp_iface:
            return True

        _config_ifname, config_iface = tap.get_by_name(self.cfg, ifname)
        if not config_iface:
            return True

        if self.vpp.tap_is_lcp(ifname):
            return False

        if (
            "name" in config_iface["host"]
            and config_iface["host"]["name"] != vpp_tap.host_if_name
        ):
            return True
        if (
            "mtu" in config_iface["host"]
            and config_iface["host"]["mtu"] != vpp_tap.host_mtu_size
        ):
            return True
        if "mac" in config_iface["host"] and config_iface["host"]["mac"] != str(
            vpp_tap.host_mac_addr
        ):
            return True
        if (
            "bridge" in config_iface["host"]
            and config_iface["host"]["bridge"] != vpp_tap.host_bridge
        ):
            return True
        if (
            "namespace" in config_iface["host"]
            and config_iface["host"]["namespace"] != vpp_tap.host_namespace
        ):
            return True

        return False

    def _bond_has_diff(self, ifname):
        """Returns True if the given ifname (BondEthernet0) have different attributes,
        or if either does not exist.

        Returns False if they are identical.
        """

        vpp_iface = self.vpp.get_interface_by_name(ifname)
        if (
            not vpp_iface
            or not vpp_iface.sw_if_index in self.vpp.cache["bondethernets"]
        ):
            return True

        config_ifname, config_iface = bondethernet.get_by_name(self.cfg, ifname)
        if not config_iface:
            return True

        vpp_bond = self.vpp.cache["bondethernets"][vpp_iface.sw_if_index]
        mode = bondethernet.mode_to_int(bondethernet.get_mode(self.cfg, config_ifname))
        if mode not in (-1, vpp_bond.mode):
            return True
        loadbalance = bondethernet.lb_to_int(
            bondethernet.get_lb(self.cfg, config_ifname)
        )
        if loadbalance not in (-1, vpp_bond.lb):
            return True

        return False

    def _prune_taps(self):
        """Remove all TAPs from VPP, if they are not in the config. As an exception,
        TAPs which are a part of Linux Control Plane, are left alone, to be handled
        by _prune_lcps() later."""
        removed_taps = []
        for _idx, vpp_tap in self.vpp.cache["taps"].items():
            vpp_iface = self.vpp.cache["interfaces"][vpp_tap.sw_if_index]
            vpp_ifname = vpp_iface.interface_name
            if self.vpp.is_foreign_interface(vpp_tap.sw_if_index):
                ## Owned by an external controlplane, leave it alone.
                continue
            if self.vpp.tap_is_lcp(vpp_ifname):
                continue
            if self._tap_has_diff(vpp_ifname):
                removed_taps.append(vpp_ifname)
                continue

        for ifname in removed_taps:
            cli = f"delete tap {ifname}"
            self.cli["prune"].append(cli)
            self.vpp.cache_remove_interface(ifname)
        return True

    def _prune_bondethernets(self):
        """Remove all BondEthernets from VPP, if they are not in the config. If the bond has members,
        remove those from the bond before removing the bond."""
        removed_interfaces = []
        removed_bondethernet_members = []
        for idx, bond in self.vpp.cache["bondethernets"].items():
            if self.vpp.is_foreign_interface(idx):
                ## Owned by an external controlplane, leave it alone.
                continue
            vpp_ifname = bond.interface_name
            _config_ifname, config_iface = bondethernet.get_by_name(
                self.cfg, vpp_ifname
            )

            if self._bond_has_diff(vpp_ifname):
                self._prune_addresses(vpp_ifname, [])
                self._prune_unnumbered_usage(vpp_ifname)
                for member in self.vpp.cache["bondethernet_members"][idx]:
                    member_ifname = self.vpp.cache["interfaces"][member].interface_name
                    cli = f"bond del {member_ifname}"
                    self.cli["prune"].append(cli)
                    removed_bondethernet_members.append(member_ifname)
                cli = f"delete bond {vpp_ifname}"
                self.cli["prune"].append(cli)
                removed_interfaces.append(vpp_ifname)
                continue

            for member in self.vpp.cache["bondethernet_members"][idx]:
                member_ifname = self.vpp.cache["interfaces"][member].interface_name
                if (
                    "interfaces" in config_iface
                    and not member_ifname in config_iface["interfaces"]
                ):
                    cli = f"bond del {member_ifname}"
                    self.cli["prune"].append(cli)
                    removed_bondethernet_members.append(member_ifname)
            addresses = []
            if "addresses" in config_iface:
                addresses = config_iface["addresses"]
            self._prune_addresses(vpp_ifname, addresses)
            self.logger.debug(f"BondEthernet OK: {vpp_ifname}")

        for ifname in removed_bondethernet_members:
            self.vpp.cache_remove_bondethernet_member(ifname)

        for ifname in removed_interfaces:
            self.vpp.cache_remove_interface(ifname)

        return True

    def _prune_vxlan_tunnels(self):
        """Remove all VXLAN Tunnels from VPP, if they are not in the config. If they are in the config
        but with differing attributes, remove them also."""
        removed_interfaces = []
        for idx, vpp_vxlan in self.vpp.cache["vxlan_tunnels"].items():
            if self.vpp.is_foreign_interface(idx):
                ## Owned by an external controlplane, leave it alone.
                continue
            vpp_ifname = self.vpp.cache["interfaces"][idx].interface_name
            config_ifname, config_iface = vxlan_tunnel.get_by_name(self.cfg, vpp_ifname)
            if not config_iface or self._vxlan_tunnel_has_diff(config_ifname):
                self._prune_addresses(vpp_ifname, [])
                cli = (
                    f"create vxlan tunnel instance {vpp_vxlan.instance} "
                    f"src {vpp_vxlan.src_address} dst {vpp_vxlan.dst_address} vni {vpp_vxlan.vni} del"
                )
                self.cli["prune"].append(cli)
                removed_interfaces.append(vpp_ifname)
                continue
            config_ifname, config_iface = interface.get_by_name(self.cfg, vpp_ifname)
            if config_iface:
                addresses = []
                if "addresses" in config_iface:
                    addresses = config_iface["addresses"]
                self._prune_addresses(vpp_ifname, addresses)
            self.logger.debug(f"VXLAN Tunnel OK: {vpp_ifname}")

        for ifname in removed_interfaces:
            self.vpp.cache_remove_vxlan_tunnel(ifname)
            self.vpp.cache_remove_interface(ifname)

        return True

    def _prune_sub_interfaces(self):
        """Remove interfaces from VPP if they are not in the config, if their encapsulation is different,
        or if the BondEthernet they reside on is different.
        Start with inner-most (QinQ/QinAD), then Dot1Q/Dot1AD."""
        removed_interfaces = []
        for numtags in [2, 1]:
            for vpp_ifname in self.vpp.get_sub_interfaces():
                vpp_iface = self.vpp.get_interface_by_name(vpp_ifname)
                if not vpp_iface or vpp_iface.sub_number_of_tags != numtags:
                    continue

                if self.vpp.tap_is_lcp(vpp_ifname):
                    continue

                prune = False
                _config_ifname, config_iface = interface.get_by_name(
                    self.cfg, vpp_ifname
                )
                if not config_iface:
                    prune = True
                elif (
                    vpp_iface.interface_dev_type == "bond"
                    and vpp_iface.sub_number_of_tags > 0
                ):
                    (
                        config_parent_ifname,
                        _config_parent_iface,
                    ) = interface.get_parent_by_name(self.cfg, vpp_ifname)
                    if self._bond_has_diff(config_parent_ifname):
                        prune = True

                config_encap = interface.get_encapsulation(self.cfg, vpp_ifname)
                vpp_encap = self._get_encapsulation(vpp_iface)
                if config_encap != vpp_encap:
                    prune = True

                if prune:
                    self._prune_addresses(vpp_ifname, [])
                    self._prune_unnumbered_usage(vpp_ifname)
                    cli = f"delete sub {vpp_ifname}"
                    self.cli["prune"].append(cli)
                    removed_interfaces.append(vpp_ifname)
                    continue

                addresses = []
                if "addresses" in config_iface:
                    addresses = config_iface["addresses"]
                self._prune_addresses(vpp_ifname, addresses)
                self.logger.debug(f"Sub Interface OK: {vpp_ifname}")

        for ifname in removed_interfaces:
            self.vpp.cache_remove_interface(ifname)

        return True

    def _prune_phys(self):
        """Set default MTU and remove IPs for PHYs that are not in the config."""
        for vpp_ifname in self.vpp.get_phys():
            vpp_iface = self.vpp.get_interface_by_name(vpp_ifname)
            if not vpp_iface:
                continue

            _config_ifname, config_iface = interface.get_by_name(self.cfg, vpp_ifname)
            if not config_iface:
                ## Interfaces were sent DOWN in the _prune_admin_state() step previously
                self._prune_addresses(vpp_ifname, [])
                if vpp_iface.link_mtu != 9000:
                    cli = f"set interface mtu 9000 {vpp_ifname}"
                    self.cli["prune"].append(cli)
                continue
            addresses = []
            if "addresses" in config_iface:
                addresses = config_iface["addresses"]
            self._prune_addresses(vpp_ifname, addresses)
            self.logger.debug(f"Interface OK: {vpp_ifname}")
        return True

    def _parent_iface_by_encap(self, sup_sw_if_index, outer, dot1ad=True):
        """Returns the sw_if_index of an interface on a given super_sw_if_index with given dot1q/dot1ad outer and inner-dot1q=0,
        in other words the intermediary Dot1Q/Dot1AD belonging to a QinX interface. If the interface doesn't exist, None is
        returned."""
        for idx, iface in self.vpp.cache["interfaces"].items():
            if iface.sup_sw_if_index != sup_sw_if_index:
                continue
            if iface.sub_inner_vlan_id > 0:
                continue
            if dot1ad and (iface.sub_if_flags & 8) and iface.sub_outer_vlan_id == outer:
                self.logger.debug(f"match: {iface.interface_name} (dot1ad)")
                return idx
            if (
                not dot1ad
                and not (iface.sub_if_flags & 8)
                and iface.sub_outer_vlan_id == outer
            ):
                self.logger.debug(f"match: {iface.interface_name} (dot1q)")
                return idx
        return None

    def _get_encapsulation(self, iface):
        """Return a dictionary-based encapsulation of the sub-interface, which helps comparing them to the same object
        returned by config.interface.get_encapsulation()."""
        if iface.sub_if_flags & 8:
            dot1ad = iface.sub_outer_vlan_id
            dot1q = 0
        else:
            dot1q = iface.sub_outer_vlan_id
            dot1ad = 0
        inner_dot1q = iface.sub_inner_vlan_id
        exact_match = iface.sub_if_flags & 16
        return {
            "dot1q": int(dot1q),
            "dot1ad": int(dot1ad),
            "inner-dot1q": int(inner_dot1q),
            "exact-match": bool(exact_match),
        }

    def _prune_lcps(self):
        """Remove LCPs which are not in the configuration, starting with QinQ/QinAD interfaces, then Dot1Q/Dot1AD,
        and finally PHYs/BondEthernets/Tunnels/Loopbacks. For QinX, special care is taken to ensure that
        their intermediary interface exists, and has the correct encalsulation. If the intermediary interface
        changed, the QinX LCP is removed. The same is true for Dot1Q/Dot1AD interfaces: if their encapsulation
        has changed, we will have to re-create the underlying sub-interface, so the LCP has to be removed.

        Order is important: destroying an LCP of a PHY will invalidate its Dot1Q/Dot1AD as well as their
        downstream children in Linux.
        """
        lcps = self.vpp.cache["lcps"]

        removed_lcps = []
        for numtags in [2, 1, 0]:
            for _idx, lcp_iface in lcps.items():
                vpp_iface = self.vpp.cache["interfaces"][lcp_iface.phy_sw_if_index]
                if vpp_iface.sub_number_of_tags != numtags:
                    continue
                if self.vpp.is_foreign_interface(lcp_iface.phy_sw_if_index):
                    ## The underlying interface is owned by an external controlplane,
                    ## leave its LCP alone.
                    continue
                if vpp_iface.interface_dev_type == "Loopback":
                    config_ifname, config_iface = loopback.get_by_lcp_name(
                        self.cfg, lcp_iface.host_if_name
                    )
                else:
                    config_ifname, config_iface = interface.get_by_lcp_name(
                        self.cfg, lcp_iface.host_if_name
                    )
                if not config_iface:
                    ## Interface doesn't exist in the config
                    removed_lcps.append(lcp_iface)
                    continue
                if not "lcp" in config_iface:
                    ## Interface doesn't have an LCP
                    removed_lcps.append(lcp_iface)
                    continue
                if vpp_iface.sub_number_of_tags == 2:
                    vpp_parent_idx = self._parent_iface_by_encap(
                        vpp_iface.sup_sw_if_index,
                        vpp_iface.sub_outer_vlan_id,
                        vpp_iface.sub_if_flags & 8,
                    )
                    vpp_parent_iface = self.vpp.cache["interfaces"][vpp_parent_idx]
                    parent_lcp = lcps[vpp_parent_iface.sw_if_index]
                    (
                        config_parent_ifname,
                        config_parent_iface,
                    ) = interface.get_by_lcp_name(self.cfg, parent_lcp.host_if_name)
                    if not config_parent_iface:
                        ## QinX's parent doesn't exist in the config
                        removed_lcps.append(lcp_iface)
                        continue
                    if not "lcp" in config_parent_iface:
                        ## QinX's parent doesn't have an LCP
                        removed_lcps.append(lcp_iface)
                        continue
                    if parent_lcp.host_if_name != config_parent_iface["lcp"]:
                        ## QinX's parent LCP name mismatch
                        removed_lcps.append(lcp_iface)
                        continue
                    config_parent_encap = interface.get_encapsulation(
                        self.cfg, config_parent_ifname
                    )
                    vpp_parent_encap = self._get_encapsulation(vpp_parent_iface)
                    if config_parent_encap != vpp_parent_encap:
                        ## QinX's parent encapsulation mismatch
                        removed_lcps.append(lcp_iface)
                        continue

                if vpp_iface.sub_number_of_tags > 0:
                    config_encap = interface.get_encapsulation(self.cfg, config_ifname)
                    vpp_encap = self._get_encapsulation(vpp_iface)
                    if config_encap != vpp_encap:
                        ## Encapsulation mismatch
                        removed_lcps.append(lcp_iface)
                        continue

                if vpp_iface.interface_dev_type == "Loopback":
                    ## Loopbacks will not have a PHY to check.
                    continue
                if vpp_iface.interface_dev_type == "bond":
                    bond_iface = self.vpp.cache["interfaces"][vpp_iface.sup_sw_if_index]
                    if self._bond_has_diff(bond_iface.interface_name):
                        ## If BondEthernet changed, it has to be re-created, so all LCPs must be removed.
                        removed_lcps.append(lcp_iface)
                        continue

                phy_lcp = lcps[vpp_iface.sup_sw_if_index]
                _config_phy_ifname, config_phy_iface = interface.get_by_lcp_name(
                    self.cfg, phy_lcp.host_if_name
                )
                if not config_phy_iface:
                    ## Phy doesn't exist in the config
                    removed_lcps.append(lcp_iface)
                    continue
                if not "lcp" in config_phy_iface:
                    ## Phy doesn't have an LCP
                    removed_lcps.append(lcp_iface)
                    continue
                if phy_lcp.host_if_name != config_phy_iface["lcp"]:
                    ## Phy LCP name mismatch
                    removed_lcps.append(lcp_iface)
                    continue

                self.logger.debug(
                    f"LCP OK: {lcp_iface.host_if_name} -> (vpp={vpp_iface.interface_name}, config={config_ifname})"
                )

        for lcp_iface in removed_lcps:
            vpp_ifname = self.vpp.cache["interfaces"][
                lcp_iface.phy_sw_if_index
            ].interface_name
            cli = f"lcp delete {vpp_ifname}"
            self.cli["prune"].append(cli)
            self.vpp.cache_remove_lcp(lcp_iface.host_if_name)
        return True

    def _prune_admin_state(self):
        """Set admin-state down for all interfaces that are not in the config."""
        for ifname in (
            self.vpp.get_qinx_interfaces()
            + self.vpp.get_dot1x_interfaces()
            + self.vpp.get_bondethernets()
            + self.vpp.get_phys()
            + self.vpp.get_vxlan_tunnels()
            + self.vpp.get_loopbacks()
        ):
            if not ifname in interface.get_interfaces(
                self.cfg
            ) + loopback.get_loopbacks(self.cfg):
                vpp_iface = self.vpp.get_interface_by_name(ifname)
                if not vpp_iface:
                    continue

                if self.vpp.tap_is_lcp(ifname):
                    continue

                if vpp_iface.flags & 1:  # IF_STATUS_API_FLAG_ADMIN_UP
                    cli = f"set interface state {ifname} down"
                    self.cli["prune"].append(cli)

        return True
