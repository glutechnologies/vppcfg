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
"""A vppcfg configuration module that validates MAC filters.

A MAC filter is a list of Ethernet source and/or destination MAC addresses (its
entries), the fields of the header it looks at (its mask), and what happens to a
frame that matches no entry (its miss action): 'deny' drops it, so the entries are
the frames let through; 'permit' lets it through, so the entries are the frames
dropped. An L2 interface applies a MAC filter to the frames it sends with the key
'mac-filter-output'. In VPP, each such interface gets a classify table of its own,
set as its L2 output ACL."""

import logging
import netaddr
from . import interface

FIELDS = ("dst", "src")  # in the order of the Ethernet header


def get_mac_filters(yaml):
    """Return a list of the names of all MAC filters."""
    if "mac-filters" in yaml:
        return list(yaml["mac-filters"])
    return []


def get_by_name(yaml, name):
    """Return the MAC filter by name, if it exists. Return None,None otherwise."""
    try:
        if name in yaml["mac-filters"]:
            return name, yaml["mac-filters"][name]
    except KeyError:
        pass
    return None, None


def normalize(mac):
    """Return a MAC address as six lowercase colon-separated octets."""
    return str(netaddr.EUI(mac, dialect=netaddr.mac_unix_expanded)).lower()


def get_mask(mac_filter):
    """Return the fields a MAC filter matches on, in the order of the Ethernet header."""
    return [field for field in FIELDS if field in mac_filter["mask"]]


def get_entries(mac_filter):
    """Return the entries of a MAC filter as a set of tuples of the normalized MAC
    addresses of its mask's fields, in the order of get_mask()."""
    mask = get_mask(mac_filter)
    ret = set()
    for entry in mac_filter.get("entries", []):
        ret.add(tuple(normalize(entry[field]) for field in mask))
    return ret


def get_interface_mac_filter(yaml, ifname):
    """Return the name of the MAC filter that interface ifname applies to the frames it
    sends, or None."""
    _ifname, iface = interface.get_by_name(yaml, ifname)
    if not iface:
        return None
    return iface.get("mac-filter-output")


def get_mac_filter_interfaces(yaml):
    """Return a list of the names of all interfaces and sub-interfaces with a
    mac-filter-output."""
    return [
        ifname
        for ifname in interface.get_interfaces(yaml)
        if get_interface_mac_filter(yaml, ifname)
    ]


def validate_mac_filters(yaml):
    """Validate the semantics of all YAML 'mac-filters' entries, and of the
    'mac-filter-output' keys of interfaces that refer to them."""
    result = True
    msgs = []
    logger = logging.getLogger("vppcfg.config")
    logger.addHandler(logging.NullHandler())

    for name, mac_filter in yaml.get("mac-filters", {}).items():
        logger.debug(f"mac-filter {name}: {mac_filter}")
        mask = mac_filter["mask"]
        if len(set(mask)) != len(mask):
            msgs.append(f"mac-filter {name} mask has a field more than once")
            result = False
        seen = set()
        for number, entry in enumerate(mac_filter.get("entries", [])):
            fields = set(entry)
            if fields != set(mask):
                msgs.append(
                    f"mac-filter {name} entry {number} has {', '.join(sorted(fields))}, "
                    f"not the fields of its mask: {', '.join(sorted(set(mask)))}"
                )
                result = False
                continue
            key = tuple(normalize(entry[field]) for field in get_mask(mac_filter))
            if key in seen:
                msgs.append(f"mac-filter {name} entry {number} is a duplicate")
                result = False
            seen.add(key)

    for ifname in get_mac_filter_interfaces(yaml):
        name = get_interface_mac_filter(yaml, ifname)
        if get_by_name(yaml, name) == (None, None):
            msgs.append(f"interface {ifname} mac-filter-output {name} does not exist")
            result = False
        if not interface.is_l2(yaml, ifname):
            msgs.append(
                f"interface {ifname} mac-filter-output {name} needs an L2 interface"
            )
            result = False

    return result, msgs
