#!/usr/bin/env python
#
# Copyright (c) 2022 Pim van Pelt
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
The functions in this file interact with the VPP API to retrieve certain
metadata, and plan configuration changes towards a given YAML target configuration.
"""
import sys
import logging
from vppcfg.config import interface
from vppcfg.config import lcp
from .vppapi import VPPApi
from .planner_prune import PlannerPruneOperations
from .planner_create import PlannerCreateOperations
from .planner_sync import PlannerSyncOperations


class Planner(PlannerPruneOperations, PlannerCreateOperations, PlannerSyncOperations):
    """The Planner class first reads the running configuration of a VPP Dataplane,
    and based on an intended target YAML configuration file, plans a path to make the
    dataplane safely reflect the target config. It first prunes (removes) objects that
    are not meant to be in the dataplane, or are in the dataplane but are not of the
    correct create-time attributes; then it creates objects that are in the configuration
    but not yet in the dataplane; and finally it syncs the configuration attributes of
    objects that can be changed at runtime."""

    def __init__(
        self,
        cfg,
        vpp_api_socket="/run/vpp/api.sock",
        vpp_json_dir=None,
    ):
        super().__init__()
        self.logger = logging.getLogger("vppcfg.planner")
        self.logger.addHandler(logging.NullHandler())

        self.vpp = VPPApi(vpp_api_socket, vpp_json_dir)
        self.cfg = cfg

        ## List of CLI calls emitted during the prune, create and sync phases.
        self.cli = {"prune": [], "create": [], "sync": []}

    def __del__(self):
        self.vpp.disconnect()

    def lcps_exist_with_lcp_enabled(self):
        """Returns False if there are LCPs defined in the configuration, but LinuxCP
        functionality is not enabled in VPP."""
        if not lcp.get_lcps(self.cfg):
            return True
        return self.vpp.lcp_enabled

    def phys_exist_in_vpp(self):
        """Return True if all PHYs in the config exist as physical interface names
        in VPP. Return False otherwise."""

        ret = True
        for ifname in interface.get_phys(self.cfg):
            if not ifname in self.vpp.cache["interface_names"]:
                self.logger.warning(f"Interface {ifname} does not exist in VPP")
                ret = False
        return ret

    def phys_exist_in_config(self):
        """Return True if all interfaces in VPP exist as physical interface names
        in the config. Return False otherwise."""

        ret = True
        for ifname in self.vpp.get_phys():
            if not ifname in interface.get_interfaces(self.cfg):
                self.logger.warning(f"Interface {ifname} does not exist in the config")
                ret = False
        return ret

    def write(self, outfile, emit_ok=False):
        """Emit the CLI contents to stdout (if outfile=='-') or a named file otherwise.
        If the 'emit_ok' flag is False, emit a warning at the top and bottom of the file.
        """
        # Assemble the intended output into a list
        output = []
        if not emit_ok:
            output.append(
                "comment { vppcfg: Planning failed, be careful with this output! }"
            )

        for phase in ["prune", "create", "sync"]:
            ncount = len(self.cli[phase])
            if ncount > 0:
                output.append(
                    f"comment {{ vppcfg {phase}: {ncount} CLI statement(s) follow }}"
                )
                output.extend(self.cli[phase])

        if not emit_ok:
            output.append(
                "comment { vppcfg: Planning failed, be careful with this output! }"
            )

        # Emit the output list to stdout or a file
        if outfile and outfile == "-":
            file = sys.stdout
            outfile = "(stdout)"
            if len(output) > 0:
                print("\n".join(output), file=file)
        else:
            with open(outfile, "w", encoding="utf-8") as file:
                if len(output) > 0:
                    print("\n".join(output), file=file)

        self.logger.info(f"Wrote {len(output)} lines to {outfile}")

    def get_commands(self):
        """Returns the CLI commands as a dictionary."""
        return self.cli
