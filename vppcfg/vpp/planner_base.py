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
Base class defining the interface expected by planner mixins.
"""

from abc import ABC
from typing import Dict, Any, List


class PlannerBase(ABC):  # pylint: disable=too-few-public-methods
    """Abstract base class defining the interface expected by planner mixins."""

    def __init__(self):
        # These attributes will be set by the concrete Planner class
        self.cfg: Dict[str, Any]
        self.vpp: Any  # VPPApi instance
        self.logger: Any  # Logger instance
        self.cli: Dict[str, List[str]]  # CLI commands grouped by operation type
