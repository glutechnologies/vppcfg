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
Planner sync operations - handles synchronization of VPP dataplane configuration.
"""

from vppcfg.config import loopback
from vppcfg.config import interface
from vppcfg.config import bondethernet
from vppcfg.config import bridgedomain
from .planner_base import PlannerBase


class PlannerSyncOperations(PlannerBase):  # pylint: disable=too-few-public-methods
    """Mixin class providing sync operations for the Planner."""

    def sync(self):
        """Synchronize the VPP Dataplane configuration for all objects in the config"""
        ret = True
        if not self._sync_loopbacks():
            self.logger.warning("Could not sync Loopbacks in VPP")
            ret = False
        if not self._sync_bondethernets():
            self.logger.warning("Could not sync bondethernets in VPP")
            ret = False
        if not self._sync_bridgedomains():
            self.logger.warning("Could not sync bridgedomains in VPP")
            ret = False
        if not self._sync_l2xcs():
            self.logger.warning("Could not sync L2 Cross Connects in VPP")
            ret = False
        if not self._sync_mtu():
            self.logger.warning("Could not sync interface MTU in VPP")
            ret = False
        if not self._sync_addresses():
            self.logger.warning("Could not sync interface addresses in VPP")
            ret = False
        if not self._sync_unnumbered():
            self.logger.warning("Could not sync unnumbered interfaces in VPP")
            ret = False
        if not self._sync_phys():
            self.logger.warning("Could not sync PHYs in VPP")
            ret = False
        if not self._sync_mpls_state():
            self.logger.warning("Could not sync interface MPLS state in VPP")
            ret = False
        if not self._sync_sflow_state():
            self.logger.warning("Could not sync interface sFlow state in VPP")
            ret = False
        if not self.sync_rx_modes():
            self.logger.warning("Could not sync interface rx-mode in VPP")
            ret = False
        if not self._sync_admin_state():
            self.logger.warning("Could not sync interface adminstate in VPP")
            ret = False
        if not self._sync_tags():
            self.logger.warning("Could not sync interface tags in VPP")
            ret = False
        return ret

    def _sync_tags(self):
        """Stamp our ownership tag onto every interface we own that does not yet
        carry a tag. Interfaces with a foreign (non-vppcfg) tag are owned by an
        external controlplane and are skipped (the get_*() enumerators already
        exclude them). This is what migrates a brownfield dataplane: on the first
        run all of our untagged interfaces get tagged, and the operation is a no-op
        on subsequent runs.

        Bridge-domains are intentionally not handled here: VPP only accepts a
        bd_tag at create time, so an existing untagged bridge-domain cannot be
        stamped. Untagged bridge-domains remain ours by the ownership rule, and new
        ones are tagged in the create() phase."""
        for ifname in (
            self.vpp.get_phys()
            + self.vpp.get_loopbacks()
            + self.vpp.get_bondethernets()
            + self.vpp.get_vxlan_tunnels()
            + self.vpp.get_sub_interfaces()
        ):
            vpp_iface = self.vpp.get_interface_by_name(ifname)
            if not vpp_iface:
                continue
            if self.vpp.tap_is_lcp(ifname):
                continue
            if vpp_iface.tag:
                ## Already tagged. Since the get_*() enumerators exclude foreign
                ## tags, a non-empty tag here is our own; nothing to do.
                continue
            cli = f"set interface tag {ifname} {self.vpp.OWN_TAG}"
            self.cli["sync"].append(cli)
        return True

    def _sync_loopbacks(self):
        """Synchronize the VPP Dataplane configuration for loopbacks"""
        for ifname in loopback.get_loopbacks(self.cfg):
            if not ifname in self.vpp.cache["interface_names"]:
                ## New loopback
                continue
            vpp_iface = self.vpp.get_interface_by_name(ifname)
            if not vpp_iface:
                continue

            config_ifname, config_iface = loopback.get_by_name(self.cfg, ifname)
            if "mac" in config_iface and config_iface["mac"] != str(
                vpp_iface.l2_address
            ):
                cli = f"set interface mac address {config_ifname} {config_iface['mac']}"
                self.cli["sync"].append(cli)
        return True

    def _sync_phys(self):
        """Synchronize the VPP Dataplane configuration for PHYs"""
        ## VPP gives the members of a BondEthernet the MAC address of the bond.
        ## Setting a member's own MAC address would take it away from the bond.
        bond_members = {
            member
            for members in self.vpp.cache["bondethernet_members"].values()
            for member in members
        }
        for ifname in interface.get_phys(self.cfg):
            if not ifname in self.vpp.cache["interface_names"]:
                ## New interface
                continue
            vpp_iface = self.vpp.get_interface_by_name(ifname)
            if not vpp_iface:
                continue

            config_ifname, config_iface = interface.get_by_name(self.cfg, ifname)
            if "mac" in config_iface and config_iface["mac"] != str(
                vpp_iface.l2_address
            ):
                if vpp_iface.sw_if_index in bond_members:
                    self.logger.debug(
                        f"Not setting MAC address of {config_ifname}, a BondEthernet member"
                    )
                    continue
                cli = f"set interface mac address {config_ifname} {config_iface['mac']}"
                self.cli["sync"].append(cli)
        return True

    def _sync_bondethernets(self):
        """Synchronize the VPP Dataplane configuration for bondethernets"""
        for ifname in bondethernet.get_bondethernets(self.cfg):
            vpp_iface = self.vpp.get_interface_by_name(ifname)
            if vpp_iface:
                vpp_members = [
                    self.vpp.cache["interfaces"][x].interface_name
                    for x in self.vpp.cache["bondethernet_members"][
                        vpp_iface.sw_if_index
                    ]
                ]
            else:
                ## New BondEthernet
                vpp_members = []

            config_bond_ifname, config_bond_iface = bondethernet.get_by_name(
                self.cfg, ifname
            )
            if not "interfaces" in config_bond_iface:
                continue
            config_ifname, config_iface = interface.get_by_name(self.cfg, ifname)
            bondmac = None
            for member_ifname in sorted(config_bond_iface["interfaces"]):
                member_ifname, member_iface = interface.get_by_name(
                    self.cfg, member_ifname
                )
                member_iface = self.vpp.get_interface_by_name(member_ifname)
                if not member_iface or member_ifname not in vpp_members:
                    if (
                        len(vpp_members) == 0
                        and member_iface
                        and member_iface.l2_address != "00:00:00:00:00:00"
                    ):
                        bondmac = member_iface.l2_address
                    cli = f"bond add {config_bond_ifname} {member_ifname}"
                    self.cli["sync"].append(cli)
            if (
                vpp_iface
                and "mac" in config_iface
                and str(vpp_iface.l2_address) != config_iface["mac"]
            ):
                cli = f"set interface mac address {config_ifname} {config_iface['mac']}"
                self.cli["sync"].append(cli)
            elif bondmac and "lcp" in config_iface:
                ## TODO(pim) - Ensure LCP has the same MAC as the BondEthernet
                ## VPP, when creating a BondEthernet, will give it an ephemeral MAC. Then, when the
                ## first member is enslaved, the MAC address changes to that of the first member.
                ## However, LinuxCP does not propagate this change to the Linux side (because there
                ## is no API callback for MAC address changes). To ensure consistency, every time we
                ## sync members, we ought to ensure the Linux device has the same MAC as its BondEthernet.
                cli = (
                    f"comment {{ ip link set {config_iface['lcp']} address {bondmac} }}"
                )
                self.cli["sync"].append(cli)
        return True

    def _sync_bridgedomains(self):
        """Synchronize the VPP Dataplane configuration for bridgedomains"""
        for ifname in bridgedomain.get_bridgedomains(self.cfg):
            instance = int(ifname[2:])
            if instance in self.vpp.cache["bridgedomains"]:
                vpp_bridge = self.vpp.cache["bridgedomains"][instance]
                bvi_sw_if_index = vpp_bridge.bvi_sw_if_index
                bridge_sw_if_index_list = [
                    x.sw_if_index for x in vpp_bridge.sw_if_details
                ]
                bridge_members = [
                    self.vpp.cache["interfaces"][x].interface_name
                    for x in bridge_sw_if_index_list
                    if x in self.vpp.cache["interfaces"]
                ]
            else:
                ## New BridgeDomain
                vpp_bridge = None
                bvi_sw_if_index = -1
                bridge_members = []

            config_bridge_ifname, config_bridge_iface = bridgedomain.get_by_name(
                self.cfg, f"bd{int(instance)}"
            )
            if vpp_bridge:
                # Sync settings on existing bridge. _create_bridgedomain() will have set them for new bridges.
                settings = bridgedomain.get_settings(self.cfg, config_bridge_ifname)
                if settings["learn"] != vpp_bridge.learn:
                    cli = f"set bridge-domain learn {int(instance)}"
                    if not settings["learn"]:
                        cli += " disable"
                    self.cli["sync"].append(cli)
                if settings["unicast-forward"] != vpp_bridge.forward:
                    cli = f"set bridge-domain forward {int(instance)}"
                    if not settings["unicast-forward"]:
                        cli += " disable"
                    self.cli["sync"].append(cli)
                if settings["unicast-flood"] != vpp_bridge.flood:
                    cli = f"set bridge-domain flood {int(instance)}"
                    if not settings["unicast-flood"]:
                        cli += " disable"
                    self.cli["sync"].append(cli)
                if settings["unknown-unicast-flood"] != vpp_bridge.uu_flood:
                    cli = f"set bridge-domain uu-flood {int(instance)}"
                    if not settings["unknown-unicast-flood"]:
                        cli += " disable"
                    self.cli["sync"].append(cli)
                if settings["arp-termination"] != vpp_bridge.arp_term:
                    cli = f"set bridge-domain arp term {int(instance)}"
                    if not settings["arp-termination"]:
                        cli += " disable"
                    self.cli["sync"].append(cli)
                if settings["arp-unicast-forward"] != vpp_bridge.arp_ufwd:
                    cli = f"set bridge-domain arp-ufwd {int(instance)}"
                    if not settings["arp-unicast-forward"]:
                        cli += " disable"
                    self.cli["sync"].append(cli)
                if settings["mac-age-minutes"] != vpp_bridge.mac_age:
                    cli = f"set bridge-domain mac-age {int(instance)} {int(settings['mac-age-minutes'])}"
                    self.cli["sync"].append(cli)

            if "bvi" in config_bridge_iface:
                bviname = config_bridge_iface["bvi"]
                bvi_iface = self.vpp.get_interface_by_name(bviname)
                if not bvi_iface or bvi_iface.sw_if_index != bvi_sw_if_index:
                    cli = f"set interface l2 bridge {bviname} {int(instance)} bvi"
                    self.cli["sync"].append(cli)

            if "interfaces" in config_bridge_iface:
                for member_ifname in config_bridge_iface["interfaces"]:
                    member_ifname, _member_iface = interface.get_by_name(
                        self.cfg, member_ifname
                    )
                    if not member_ifname in bridge_members:
                        cli = f"set interface l2 bridge {member_ifname} {int(instance)}"
                        self.cli["sync"].append(cli)
                        operation = "disable"
                        if interface.is_qinx(self.cfg, member_ifname):
                            operation = "pop 2"
                        elif interface.is_sub(self.cfg, member_ifname):
                            operation = "pop 1"
                        cli = (
                            f"set interface l2 tag-rewrite {member_ifname} {operation}"
                        )
                        self.cli["sync"].append(cli)
        return True

    def _sync_l2xcs(self):
        """Synchronize the VPP Dataplane configuration for L2 cross connects"""
        for ifname in interface.get_l2xc_interfaces(self.cfg):
            config_rx_ifname, config_rx_iface = interface.get_by_name(self.cfg, ifname)
            config_tx_ifname, _config_tx_iface = interface.get_by_name(
                self.cfg, config_rx_iface["l2xc"]
            )
            vpp_rx_iface = self.vpp.get_interface_by_name(config_rx_ifname)
            vpp_tx_iface = self.vpp.get_interface_by_name(config_tx_ifname)

            l2xc_changed = False
            if not vpp_rx_iface or not vpp_tx_iface:
                l2xc_changed = True
            elif not vpp_rx_iface.sw_if_index in self.vpp.cache["l2xcs"]:
                l2xc_changed = True
            elif (
                not vpp_tx_iface.sw_if_index
                == self.vpp.cache["l2xcs"][vpp_rx_iface.sw_if_index].tx_sw_if_index
            ):
                l2xc_changed = True

            if l2xc_changed:
                cli = f"set interface l2 xconnect {config_rx_ifname} {config_tx_ifname}"
                self.cli["sync"].append(cli)

                operation = "disable"
                if interface.is_qinx(self.cfg, config_rx_ifname):
                    operation = "pop 2"
                elif interface.is_sub(self.cfg, config_rx_ifname):
                    operation = "pop 1"
                cli = f"set interface l2 tag-rewrite {config_rx_ifname} {operation}"
                self.cli["sync"].append(cli)
        return True

    def _sync_mtu_direction(self, shrink=True):
        """Synchronize the VPP Dataplane packet MTU, where 'shrink' determines the
        direction (if shrink is True, go from inner-most (QinQ) to outer-most (untagged),
        and the other direction if shrink is False"""
        if shrink:
            tag_list = [2, 1, 0]
        else:
            tag_list = [0, 1, 2]

        for numtags in tag_list:
            for ifname in loopback.get_loopbacks(self.cfg) + interface.get_interfaces(
                self.cfg
            ):
                if numtags == 0 and interface.is_sub(self.cfg, ifname):
                    continue
                if numtags == 1 and not interface.is_sub(self.cfg, ifname):
                    continue
                if numtags == 1 and interface.is_qinx(self.cfg, ifname):
                    continue
                if numtags == 2 and not interface.is_qinx(self.cfg, ifname):
                    continue
                config_mtu = 1500
                vpp_mtu = 9000
                if ifname.startswith("loop"):
                    _iface = self.vpp.get_interface_by_name(ifname)
                    if _iface:
                        vpp_mtu = _iface.mtu[0]
                    vpp_ifname, config_iface = loopback.get_by_name(self.cfg, ifname)
                    if "mtu" in config_iface:
                        config_mtu = config_iface["mtu"]
                else:
                    if numtags > 0:
                        vpp_mtu = 0
                    _iface = self.vpp.get_interface_by_name(ifname)
                    if _iface:
                        vpp_mtu = _iface.mtu[0]
                    vpp_ifname, config_iface = interface.get_by_name(self.cfg, ifname)
                    config_mtu = interface.get_mtu(self.cfg, ifname)

                if shrink and config_mtu < vpp_mtu:
                    cli = f"set interface mtu packet {int(config_mtu)} {vpp_ifname}"
                    self.cli["sync"].append(cli)
                elif not shrink and config_mtu > vpp_mtu:
                    cli = f"set interface mtu packet {int(config_mtu)} {vpp_ifname}"
                    self.cli["sync"].append(cli)
        return True

    def _sync_link_mtu_direction(self, shrink=True):
        """Synchronize the VPP Dataplane max frame size (link MTU), where 'shrink' determines the
        direction (if shrink is True, go from inner-most (QinQ) to outer-most (untagged),
        and the other direction if shrink is False"""
        lcp_tap_sw_if_indexes = {
            lcp.host_sw_if_index for lcp in self.vpp.cache["lcps"].values()
        }
        for _idx, vpp_iface in self.vpp.cache["interfaces"].items():
            if vpp_iface.sub_number_of_tags != 0:
                continue
            if vpp_iface.interface_dev_type in ["local", "Loopback", "VXLAN", "virtio"]:
                continue
            if vpp_iface.sw_if_index in lcp_tap_sw_if_indexes:
                continue
            if self.vpp.is_foreign_interface(vpp_iface.sw_if_index):
                ## Owned by an external controlplane (foreign tag); leave it alone.
                continue

            _config_ifname, config_iface = interface.get_by_name(
                self.cfg, vpp_iface.interface_name
            )
            if not config_iface:
                self.logger.warning(
                    f"Interface {vpp_iface.interface_name} exists in VPP but not in config, this is dangerous"
                )
                continue
            if not interface.is_phy(self.cfg, vpp_iface.interface_name):
                continue
            if vpp_iface.interface_dev_type in ["RDMA interface", "rdma"]:
                ## RDMA devices do not allow setting the Max Frame Size (link MTU).
                continue
            config_mtu = interface.get_mtu(self.cfg, vpp_iface.interface_name)

            if (
                vpp_iface.interface_dev_type == "bond"
                and vpp_iface.link_mtu < config_mtu
            ):
                self.logger.warning(
                    f"{vpp_iface.interface_name} has a Max Frame Size ({vpp_iface.link_mtu}) "
                    "lower than desired MTU ({config_mtu}), this is unsupported"
                )
                continue

            if shrink and config_mtu < vpp_iface.link_mtu:
                ## If the interface is up, temporarily down it in order to change the Max Frame Size
                if vpp_iface.flags & 1:  # IF_STATUS_API_FLAG_ADMIN_UP
                    cli = f"set interface state {vpp_iface.interface_name} down"
                    self.cli["sync"].append(cli)

                cli = f"set interface mtu {int(config_mtu)} {vpp_iface.interface_name}"
                self.cli["sync"].append(cli)

                if vpp_iface.flags & 1:  # IF_STATUS_API_FLAG_ADMIN_UP
                    cli = f"set interface state {vpp_iface.interface_name} up"
                    self.cli["sync"].append(cli)
            elif not shrink and config_mtu > vpp_iface.link_mtu:
                ## If the interface is up, temporarily down it in order to change the Max Frame Size
                if vpp_iface.flags & 1:  # IF_STATUS_API_FLAG_ADMIN_UP
                    cli = f"set interface state {vpp_iface.interface_name} down"
                    self.cli["sync"].append(cli)

                cli = f"set interface mtu {int(config_mtu)} {vpp_iface.interface_name}"
                self.cli["sync"].append(cli)

                if vpp_iface.flags & 1:  # IF_STATUS_API_FLAG_ADMIN_UP
                    cli = f"set interface state {vpp_iface.interface_name} up"
                    self.cli["sync"].append(cli)
        return True

    def _sync_mtu(self):
        """Synchronize the VPP Dataplane configuration for interface MTU"""
        ret = True
        if not self._sync_link_mtu_direction(shrink=False):
            self.logger.warning(
                "Could not sync growing interface Max Frame Size in VPP"
            )
            ret = False
        if not self._sync_link_mtu_direction(shrink=True):
            self.logger.warning(
                "Could not sync shrinking interface Max Frame Size in VPP"
            )
            ret = False
        if not self._sync_mtu_direction(shrink=True):
            self.logger.warning("Could not sync shrinking interface MTU in VPP")
            ret = False
        if not self._sync_mtu_direction(shrink=False):
            self.logger.warning("Could not sync growing interface MTU in VPP")
            ret = False
        return ret

    def _sync_sflow_state(self):
        """Synchronize the VPP Dataplane configuration and phy sFlow state"""

        if "sflow" in self.cfg and self.vpp.cache["sflow"]:
            if "header-bytes" in self.cfg["sflow"]:
                if (
                    self.vpp.cache["sflow"]["header-bytes"]
                    != self.cfg["sflow"]["header-bytes"]
                ):
                    cli = f"sflow header-bytes {self.cfg['sflow']['header-bytes']}"
                    self.cli["sync"].append(cli)
            if "polling-interval" in self.cfg["sflow"]:
                if (
                    self.vpp.cache["sflow"]["polling-interval"]
                    != self.cfg["sflow"]["polling-interval"]
                ):
                    cli = f"sflow polling-interval {self.cfg['sflow']['polling-interval']}"
                    self.cli["sync"].append(cli)
            if "sampling-rate" in self.cfg["sflow"]:
                if (
                    self.vpp.cache["sflow"]["sampling-rate"]
                    != self.cfg["sflow"]["sampling-rate"]
                ):
                    cli = f"sflow sampling-rate {self.cfg['sflow']['sampling-rate']}"
                    self.cli["sync"].append(cli)

        for ifname in interface.get_interfaces(self.cfg):
            vpp_ifname, config_iface = interface.get_by_name(self.cfg, ifname)

            try:
                config_sflow = config_iface["sflow"]
            except KeyError:
                config_sflow = False

            vpp_sflow = False
            if vpp_ifname in self.vpp.cache["interface_names"]:
                hw_if_index = self.vpp.cache["interface_names"][vpp_ifname]
                try:
                    vpp_sflow = self.vpp.cache["interface_sflow"][hw_if_index]
                except KeyError:
                    pass
            if vpp_sflow != config_sflow:
                if config_sflow:
                    cli = f"sflow enable {vpp_ifname}"
                else:
                    cli = f"sflow enable-disable {vpp_ifname} disable"
                self.cli["sync"].append(cli)
        return True

    def sync_rx_modes(self):
        """Synchronize the rx-mode of interfaces and loopbacks that set one: of
        their own receive queues (PHYs and TAPs) and of the TAP of their LCP.

        The TAP of an LCP that this run creates does not exist yet, so it cannot
        be named here: Applier callers run this again once the create phase is
        applied (see vppcfg.py)."""
        for ifname in interface.get_interfaces(self.cfg) + loopback.get_loopbacks(
            self.cfg
        ):
            mode = interface.get_rx_mode(self.cfg, ifname)
            if not mode:
                continue
            targets = []
            if interface.has_rx_queues(self.cfg, ifname):
                targets.append(ifname)
            tap_ifname = self.vpp.get_lcp_tap_name(ifname)
            if tap_ifname:
                targets.append(tap_ifname)
            for target in targets:
                vpp_modes = self.vpp.get_rx_modes(target)
                if vpp_modes and vpp_modes != {mode}:
                    cli = f"set interface rx-mode {target} {mode}"
                    self.cli["sync"].append(cli)
        return True

    def _sync_mpls_state(self):
        """Synchronize the VPP Dataplane configuration for interface and loopback MPLS state"""
        for ifname in loopback.get_loopbacks(self.cfg) + interface.get_interfaces(
            self.cfg
        ):
            if ifname.startswith("loop"):
                vpp_ifname, config_iface = loopback.get_by_name(self.cfg, ifname)
            else:
                vpp_ifname, config_iface = interface.get_by_name(self.cfg, ifname)

            try:
                config_mpls = config_iface["mpls"]
            except KeyError:
                config_mpls = False

            vpp_mpls = False
            if vpp_ifname in self.vpp.cache["interface_names"]:
                sw_if_index = self.vpp.cache["interface_names"][vpp_ifname]
                try:
                    vpp_mpls = self.vpp.cache["interface_mpls"][sw_if_index]
                except KeyError:
                    pass
            if vpp_mpls != config_mpls:
                state = "disable"
                if config_mpls:
                    state = "enable"
                cli = f"set interface mpls {vpp_ifname} {state}"
                self.cli["sync"].append(cli)
        return True

    def _sync_unnumbered(self):
        """Synchronize the VPP Dataplane configuration for unnumbered interface"""
        for ifname in loopback.get_loopbacks(self.cfg) + interface.get_interfaces(
            self.cfg
        ):
            if ifname.startswith("loop"):
                config_ifname, config_iface = loopback.get_by_name(self.cfg, ifname)
            else:
                config_ifname, config_iface = interface.get_by_name(self.cfg, ifname)

            config_unnumbered_ifname = None
            if "unnumbered" in config_iface:
                config_unnumbered_ifname = config_iface["unnumbered"]
            self.logger.debug(
                f"unnumbered iface {config_ifname} use {config_unnumbered_ifname}"
            )

            vpp_iface = self.vpp.get_interface_by_name(config_ifname)
            vpp_iface_unnumbered = self.vpp.get_interface_by_name(
                config_unnumbered_ifname
            )
            self.logger.debug(
                f"unnumbered iface {vpp_iface} use {vpp_iface_unnumbered}"
            )

            if not config_unnumbered_ifname:
                if (
                    vpp_iface
                    and vpp_iface.sw_if_index in self.vpp.cache["interface_unnumbered"]
                ):
                    cli = f"set interface unnumbered del {config_ifname}"
                    self.cli["sync"].append(cli)
                    del self.vpp.cache["interface_unnumbered"][vpp_iface.sw_if_index]
                    continue
                continue

            if (
                vpp_iface_unnumbered
                and vpp_iface
                and vpp_iface.sw_if_index in self.vpp.cache["interface_unnumbered"]
            ):
                if (
                    self.vpp.cache["interface_unnumbered"][vpp_iface.sw_if_index]
                    == vpp_iface_unnumbered.sw_if_index
                ):
                    continue

            cli = f"set interface unnumbered {config_ifname} use {config_unnumbered_ifname}"
            self.cli["sync"].append(cli)

        return True

    def _sync_addresses(self):
        """Synchronize the VPP Dataplane configuration for interface addresses"""
        for ifname in loopback.get_loopbacks(self.cfg) + interface.get_interfaces(
            self.cfg
        ):
            config_addresses = []
            vpp_addresses = []
            if ifname.startswith("loop"):
                vpp_ifname, config_iface = loopback.get_by_name(self.cfg, ifname)
                if "addresses" in config_iface:
                    config_addresses = config_iface["addresses"]
            else:
                vpp_ifname, config_iface = interface.get_by_name(self.cfg, ifname)
                if "addresses" in config_iface:
                    config_addresses = config_iface["addresses"]
            if vpp_ifname in self.vpp.cache["interface_names"]:
                _iface = self.vpp.get_interface_by_name(vpp_ifname)
                if _iface.sw_if_index in self.vpp.cache["interface_addresses"]:
                    vpp_addresses = [
                        str(x)
                        for x in self.vpp.cache["interface_addresses"][
                            _iface.sw_if_index
                        ]
                    ]
            for addr in config_addresses:
                if addr in vpp_addresses:
                    continue
                cli = f"set interface ip address {vpp_ifname} {addr}"
                self.cli["sync"].append(cli)
        return True

    def _sync_admin_state(self):
        """Synchronize the VPP Dataplane configuration for interface admin state"""
        for ifname in interface.get_interfaces(self.cfg) + loopback.get_loopbacks(
            self.cfg
        ):
            if ifname.startswith("loop"):
                vpp_ifname, _config_iface = loopback.get_by_name(self.cfg, ifname)
                config_admin_state = 1
            else:
                vpp_ifname, _config_iface = interface.get_by_name(self.cfg, ifname)
                config_admin_state = interface.get_admin_state(self.cfg, ifname)

            vpp_admin_state = 0
            _iface = self.vpp.get_interface_by_name(vpp_ifname)
            if _iface:
                vpp_admin_state = _iface.flags & 1  # IF_STATUS_API_FLAG_ADMIN_UP

            if config_admin_state == vpp_admin_state:
                continue
            state = "up"
            if config_admin_state == 0:
                state = "down"
            cli = f"set interface state {vpp_ifname} {state}"
            self.cli["sync"].append(cli)
        return True
