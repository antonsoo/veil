"""Construct synthetic literals and cross-check each address with libc inet_pton.

Scope names are opaque fixtures, not interfaces on this machine. Native parsing
validates the address bytes before the '%' only; no DNS/interface lookup occurs.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path

cases = []
for index, address in enumerate(
    [
        "2001:db8:ab:cd::c000:221",
        "fd42:1:2:3::c000:221",
        "fe80::c000:221",
        "64:ff9b::c000:221",
        "64:ff9b:1:2::c000:221",
        "5f00:1::c000:221",
        "::ffff:c000:221",
    ]
):
    value = ipaddress.IPv6Address(address)
    native = socket.inet_pton(socket.AF_INET6, address)
    mixed = ":".join(value.exploded.split(":")[:6]) + ":192.0.2.33"
    forms = [value.compressed, value.exploded, mixed, mixed.upper()]
    scopes = [""] + (["%en0", "%13", "%25eth0%2D1"] if address.startswith("fe80:") else [])
    for f, form in enumerate(forms):
        assert socket.inet_pton(socket.AF_INET6, form) == native == value.packed
        for s, scope in enumerate(scopes):
            for c, (prefix, suffix) in enumerate(
                [("peer=[", "]:443\n"), ("route=", "/64\n"), ("Host ", ". Please retry.\n")]
            ):
                cases.append(
                    {
                        "id": f"generated-{index}-{f}-{s}-{c}",
                        "literal": form + scope,
                        "prefix": prefix,
                        "suffix": suffix,
                        "mask": True,
                        "nativeAddressHex": native.hex(),
                    }
                )

for index, literal in enumerate(
    [
        "2001:db8::192.0.2.33",
        "2001:db8:122:344::192.0.2.33",
        "::ffff:192.0.2.33",
        "::192.0.2.33",
        "2001:db8::127.0.0.1",
        "2001:db8::0.0.0.0",
        "fe80::1%eth0.100",
    ]
):
    cases.append(
        {
            "id": f"regression-{index}",
            "literal": literal,
            "prefix": "peer=",
            "suffix": "\n",
            "mask": True,
            "nativeAddressHex": socket.inet_pton(socket.AF_INET6, literal.partition("%")[0]).hex(),
        }
    )

for index, literal in enumerate(
    [
        "::",
        "::1",
        "::0.0.0.1",
        "::ffff:127.0.0.1",
        "::ffff:7f00:1",
        "::ffff:0.0.0.0",
        "::ffff:255.255.255.0",
        "::ffff:ffff:ff00",
        "be::",
        "1::2",
        "::2",
        "fe80::1%",
        "fe80::1%%en0",
        "fe80::1%25eth0%2G1",
        "2001:db8::192.0.2.33%",
        "2001:db8::192.0.2.33%%en0",
        "2001:db8::192.0.2.33:abcd",
        "2001:db8::192.0.2.33.4",
        "2001:db8:::192.0.2.33",
        "2001:db8::256.0.2.33",
        "2001:db8::192.000.2.33",
        "12345:db8::192.0.2.33",
        "2001:db8:0:0:0:0:0:192.0.2.33",
    ]
):
    cases.append(
        {
            "id": f"control-{index}",
            "literal": literal,
            "prefix": "peer=[",
            "suffix": "]\n",
            "mask": False,
        }
    )
Path(__file__).with_name("cases.json").write_text(
    json.dumps({"synthetic": True, "cases": cases}, indent=2) + "\n"
)
print(f"{len(cases)} synthetic cases, {sum(c['mask'] for c in cases)} whole-literal expectations")
