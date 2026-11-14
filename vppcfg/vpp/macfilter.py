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
"""MAC filters as VPP classify tables: the CLI statements that make one, and the
reading of one back from the classify tables of a running VPP.

A MAC filter is one classify table that matches the first 16 bytes of the frame
(skip 0, match 1), where the destination MAC is bytes 0-5 and the source MAC bytes
6-11. Its miss next index is the miss action of the filter, and each of its sessions
is an entry, with the other action as its hit next index. For an ACL, next index 0
denies and ~0 permits."""

from vppcfg.config import macfilter

NEXT_INDEX = {"deny": 0, "permit": 2**32 - 1}
HIT = {"deny": "permit", "permit": "deny"}
OFFSET = {"dst": 0, "src": 6}

## The applier swaps this word for the index of the classify table that the last
## 'classify table' statement before it created: VPP picks that index itself.
NEW_TABLE = "$new-table"


def mask_bytes(mask):
    """The 16 byte classify mask of a list of fields."""
    ret = bytearray(16)
    for field in mask:
        ret[OFFSET[field] : OFFSET[field] + 6] = b"\xff" * 6
    return bytes(ret)


def match_bytes(mask, values):
    """The 16 byte classify match of the MAC addresses `values` of the fields `mask`."""
    ret = bytearray(16)
    for field, mac in zip(mask, values):
        ret[OFFSET[field] : OFFSET[field] + 6] = bytes.fromhex(mac.replace(":", ""))
    return bytes(ret)


def mac_from_bytes(octets):
    """Six bytes as a lowercase colon-separated MAC address."""
    return ":".join(f"{octet:02x}" for octet in octets)


def session_next_index(session):
    """The hit next index of a classify session read from VPP. VPP keeps it in 16
    bits, so the ~0 of 'permit' reads back as 0xffff."""
    if session.hit_next_index == 2**16 - 1:
        return NEXT_INDEX["permit"]
    return session.hit_next_index


def table_form(table):
    """The (mask, miss) of a classify table read from VPP when it is a MAC filter,
    else None."""
    info = table["info"]
    if info.skip_n_vectors != 0 or info.match_n_vectors != 1:
        return None
    if info.next_table_index != 2**32 - 1:
        return None
    mask = None
    for fields in (["dst"], ["src"], ["dst", "src"]):
        if bytes(info.mask) == mask_bytes(fields):
            mask = fields
    miss = [key for key, value in NEXT_INDEX.items() if value == info.miss_next_index]
    if mask is None or not miss:
        return None
    return mask, miss[0]


def table_entries(table, mask, miss):
    """The entries of a MAC filter table read from VPP, as get_entries() returns those
    of a configured one; None when a session is not an entry of a (mask, miss) filter.
    """
    ret = set()
    hit = NEXT_INDEX[HIT[miss]]
    for session in table["sessions"]:
        if session_next_index(session) != hit:
            return None
        key = bytes(session.match)
        ret.add(tuple(mac_from_bytes(key[OFFSET[f] : OFFSET[f] + 6]) for f in mask))
    return ret


def cli_table(mac_filter):
    """The statement that creates the classify table of a MAC filter."""
    mask = macfilter.get_mask(mac_filter)
    return f"classify table acl-miss-next {mac_filter['miss']} mask l2 {' '.join(mask)}"


def cli_session(table, mask, values, miss, delete=False):
    """The statement that adds (or deletes) one entry of a MAC filter in table
    `table`, which is an index or NEW_TABLE."""
    match = " ".join(f"{field} {mac}" for field, mac in zip(mask, values))
    if delete:
        return f"classify session del table-index {table} match l2 {match}"
    return f"classify session acl-hit-next {HIT[miss]} table-index {table} match l2 {match}"
