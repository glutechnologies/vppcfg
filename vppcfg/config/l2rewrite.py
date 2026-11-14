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
"""A vppcfg configuration module that validates L2 VLAN tag rewrites.

An L2 interface (a bridge-domain member or an L2XC source) rewrites the VLAN tags
of the frames it receives: it pops the outer 'pop' tags (0, 1 or 2) and then pushes
the tags of 'push' (none, an outer one, or an outer and an inner one), and undoes
that on the frames it sends. Without 'l2-rewrite', vppcfg pops all the tags of the
encapsulation of a sub-interface, and nothing on an untagged interface. With
'l2-rewrite', that is replaced: an empty 'l2-rewrite: {}' rewrites nothing, and a
'pop' with a 'push' translates the tags (VPP's 'translate 1-1' and friends).

A pushed tag is a VLAN id with an optional PCP (0-7) and DEI, which together make the
16 bit TCI that VPP pushes."""

import logging
from . import interface
from . import bridgedomain


def get_number_of_tags(yaml, ifname):
    """Return the number of VLAN tags that the encapsulation of ifname matches."""
    if not interface.is_sub(yaml, ifname):
        return 0
    if interface.is_qinx(yaml, ifname):
        return 2
    return 1


def tci(vid, pcp=0, dei=False):
    """The 16 bit Tag Control Information of a VLAN tag."""
    return (int(pcp) << 13) | (int(bool(dei)) << 12) | int(vid)


def has_default(yaml, ifname):
    """Return True if vppcfg rewrites the tags of ifname when it has no 'l2-rewrite':
    bridge-domain members and L2XC sources pop all the tags of their encapsulation."""
    return bridgedomain.is_bridge_interface(
        yaml, ifname
    ) or interface.is_l2xc_interface(yaml, ifname)


def normalize(rewrite):
    """Return an 'l2-rewrite' dictionary as {'pop': int, 'push': [(tpid, tci), ...]},
    where the push list holds the outer tag first, and tpid is 'dot1q' or 'dot1ad'."""
    push = []
    config_push = rewrite.get("push", {})
    for tpid in ("dot1q", "dot1ad"):
        if tpid in config_push:
            push.append(
                (
                    tpid,
                    tci(
                        config_push[tpid],
                        config_push.get("pcp", 0),
                        config_push.get("dei", False),
                    ),
                )
            )
    if "inner-dot1q" in config_push:
        push.append(
            (
                "dot1q",
                tci(
                    config_push["inner-dot1q"],
                    config_push.get("inner-pcp", 0),
                    config_push.get("inner-dei", False),
                ),
            )
        )
    return {"pop": int(rewrite.get("pop", 0)), "push": push}


def get_l2_rewrite(yaml, ifname):
    """Return the tag rewrite of ifname, as normalize() does, or None when vppcfg does
    not manage the tag rewrite of ifname."""
    _ifname, iface = interface.get_by_name(yaml, ifname)
    if not iface:
        return None
    if "l2-rewrite" in iface:
        return normalize(iface["l2-rewrite"])
    if has_default(yaml, ifname):
        return {"pop": get_number_of_tags(yaml, ifname), "push": []}
    return None


def get_l2_rewrite_interfaces(yaml):
    """Return a list of the names of all interfaces and sub-interfaces whose tag rewrite
    vppcfg manages."""
    return [
        ifname
        for ifname in interface.get_interfaces(yaml)
        if get_l2_rewrite(yaml, ifname) is not None
    ]


def validate_l2_rewrites(yaml):
    """Validate the semantics of all 'l2-rewrite' keys of interfaces and
    sub-interfaces."""
    result = True
    msgs = []
    logger = logging.getLogger("vppcfg.config")
    logger.addHandler(logging.NullHandler())

    for ifname in interface.get_interfaces(yaml):
        _ifname, iface = interface.get_by_name(yaml, ifname)
        if not iface or "l2-rewrite" not in iface:
            continue
        rewrite = iface["l2-rewrite"]
        logger.debug(f"l2-rewrite {ifname}: {rewrite}")
        if not interface.is_l2(yaml, ifname):
            msgs.append(f"interface {ifname} l2-rewrite needs an L2 interface")
            result = False
        tags = get_number_of_tags(yaml, ifname)
        if rewrite.get("pop", 0) > tags:
            msgs.append(
                f"interface {ifname} l2-rewrite pops {rewrite['pop']} tags, "
                f"but its encapsulation has {tags}"
            )
            result = False
        if "push" not in rewrite:
            continue
        push = rewrite["push"]
        if ("dot1q" in push) == ("dot1ad" in push):
            msgs.append(
                f"interface {ifname} l2-rewrite push needs one of dot1q or dot1ad"
            )
            result = False
        for key in ("inner-pcp", "inner-dei"):
            if key in push and "inner-dot1q" not in push:
                msgs.append(
                    f"interface {ifname} l2-rewrite push has {key} without inner-dot1q"
                )
                result = False

    return result, msgs
