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
from .macfilter import NEW_TABLE


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

        cli_calls = 0
        cli_success = 0
        new_table = None
        for phase, cmds in self.cli.items():
            for cmd in cmds:
                cli_calls += 1

                if NEW_TABLE in cmd.split():
                    if new_table is None:
                        self.logger.error(f"No classify table was created for: {cmd}")
                        continue
                    cmd = " ".join(
                        str(new_table) if word == NEW_TABLE else word
                        for word in cmd.split()
                    )
                creates_table = self.creates_classify_table(cmd)
                if creates_table:
                    new_table = None
                    before = self.classify_table_ids()

                self.logger.debug(f"{phase}: {cmd}")
                ret = self.cli_inband(cmd=cmd)
                self.logger.debug(f"Retval: {ret}")

                if ret is False:
                    self.logger.error("VPP returned error")
                elif ret.retval == 0 and creates_table:
                    created = self.classify_table_ids() - before
                    if len(created) == 1:
                        new_table = created.pop()
                        cli_success += 1
                    else:
                        self.logger.warning(f"VPP {cmd} created tables {created}")
                elif ret.retval == 0:
                    cli_success += 1
                else:
                    self.logger.warning(f"VPP {cmd} returned {ret}")

        if cli_calls == 0:
            self.logger.info("Nothing to do")
            return True

        self.logger.info(f"VPP API calls: {cli_calls}, success: {cli_success}")
        if cli_calls != cli_success:
            self.logger.warning("Not all VPP calls were successful!")
            return False
        return True

    @staticmethod
    def creates_classify_table(cmd):
        """Return True if the CLI statement cmd creates a classify table, rather
        than changing or deleting one."""
        words = cmd.split()
        return words[:2] == ["classify", "table"] and not {
            "del",
            "del-chain",
            "table",
        } & set(words[2:])

    def classify_table_ids(self):
        """Return the set of the indexes of the classify tables in VPP."""
        if not self.connected and not self.connect():
            return set()
        return set(self.vpp.api.classify_table_ids().ids)
