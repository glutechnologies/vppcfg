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
The functions in this file interact with the VPP API to modify certain
interface metadata.
"""

import logging
from .vppapi import VPPApi


class Applier(VPPApi):
    """The methods in the Applier class modify the running state in the VPP dataplane
    and will ensure that the local cache is consistent after creations and
    modifications."""

    # pylint: disable=unnecessary-pass

    def __init__(
        self,
        cfg,
        planner_cli,
        vpp_api_socket="/run/vpp/api.sock",
        vpp_json_dir=None,
        clientname="vppcfg",
    ):
        super().__init__(vpp_api_socket, vpp_json_dir, clientname)
        self.logger = logging.getLogger("vppcfg.applier")
        self.logger.addHandler(logging.NullHandler())
        self.cli = planner_cli

    def apply(self):
        """Apply the commands from self.cli to the cli_inband API call. Will eventually be
        replaced with actual API calls."""

        for phase, cmds in self.cli.items():
            for cmd in cmds:
                self.logger.debug(f"{phase}: {cmd}")
                ret = self.cli_inband(cmd=cmd)
                if ret == False:
                    self.logger.error("VPP returned error, bailing")
                    return ret
                self.logger.debug(f"Retval: {ret}")

        return True
