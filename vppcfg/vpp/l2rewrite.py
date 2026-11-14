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
# -*- coding: utf-8 -*-
"""L2 VLAN tag rewrites in VPP: the CLI statement that sets one, and the reading of
one back from the vtr_* fields of an interface's sw_interface_details.

A rewrite is {'pop': int, 'push': [(tpid, tci), ...]} as config.l2rewrite.normalize()
returns it. VPP keeps it as (vtr_op, vtr_push_dot1q, vtr_tag1, vtr_tag2): the
operation, whether the outer pushed tag is dot1q (1) or dot1ad (0), and the TCIs of
the pushed tags, outer first; fields an operation does not use read back as 0."""

## (pop, number of pushed tags) -> (VPP's vtr_op, CLI words)
OPERATIONS = {
    (0, 0): (0, "disable"),
    (0, 1): (1, "push"),
    (0, 2): (2, "push"),
    (1, 0): (3, "pop 1"),
    (2, 0): (4, "pop 2"),
    (1, 1): (5, "translate 1-1"),
    (1, 2): (6, "translate 1-2"),
    (2, 1): (7, "translate 2-1"),
    (2, 2): (8, "translate 2-2"),
}
BY_VTR_OP = {op: key for key, (op, _words) in OPERATIONS.items()}


def to_vtr(rewrite):
    """The (vtr_op, vtr_push_dot1q, vtr_tag1, vtr_tag2) that VPP reads back for a
    rewrite."""
    push = rewrite["push"]
    op, _words = OPERATIONS[(rewrite["pop"], len(push))]
    push_dot1q = 1 if push and push[0][0] == "dot1q" else 0
    tag1 = push[0][1] if len(push) > 0 else 0
    tag2 = push[1][1] if len(push) > 1 else 0
    return (op, push_dot1q, tag1, tag2)


def vtr_of(vpp_iface):
    """The (vtr_op, vtr_push_dot1q, vtr_tag1, vtr_tag2) of an interface read from VPP."""
    return (
        vpp_iface.vtr_op,
        vpp_iface.vtr_push_dot1q,
        vpp_iface.vtr_tag1,
        vpp_iface.vtr_tag2,
    )


def from_vtr(vtr):
    """The rewrite of a (vtr_op, vtr_push_dot1q, vtr_tag1, vtr_tag2), or None when VPP
    reports an operation that vppcfg does not know."""
    op, push_dot1q, tag1, tag2 = vtr
    if op not in BY_VTR_OP:
        return None
    pop, pushed = BY_VTR_OP[op]
    push = []
    if pushed > 0:
        push.append(("dot1q" if push_dot1q else "dot1ad", tag1))
    if pushed > 1:
        push.append(("dot1q", tag2))
    return {"pop": pop, "push": push}


def to_config(rewrite):
    """The 'l2-rewrite' configuration of a rewrite."""
    ret = {"pop": rewrite["pop"]}
    if not rewrite["push"]:
        return ret
    push = {}
    for (tpid, tci), prefix in zip(rewrite["push"], ("", "inner-")):
        push[f"{prefix}{tpid}"] = tci & 0xFFF
        if tci >> 13:
            push[f"{prefix}pcp"] = tci >> 13
        if tci & 0x1000:
            push[f"{prefix}dei"] = True
    ret["push"] = push
    return ret


def cli(ifname, rewrite):
    """The statement that sets the rewrite of interface ifname."""
    push = rewrite["push"]
    _op, words = OPERATIONS[(rewrite["pop"], len(push))]
    if push:
        words += f" {push[0][0]} " + " ".join(str(tci) for _tpid, tci in push)
    return f"set interface l2 tag-rewrite {ifname} {words}"
