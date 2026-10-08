from veil.detectors.ip import IpDetector

d = IpDetector()


def types(text: str) -> list[str]:
    return [e.type.value for e in d.find(text)]


def test_finds_ipv4() -> None:
    entities = d.find("connect to 10.0.0.1 please")
    assert [e.value for e in entities] == ["10.0.0.1"]
    assert entities[0].type.value == "IPV4"


def test_rejects_octet_over_255() -> None:
    assert d.find("999.999.999.999") == []


def test_finds_full_ipv6() -> None:
    entities = d.find("host 2001:0db8:0000:0000:0000:ff00:0042:8329 is up")
    assert len(entities) == 1
    assert entities[0].type.value == "IPV6"


def test_finds_compressed_ipv6() -> None:
    entities = d.find("host fe80::1 is up")
    assert len(entities) == 1
    assert entities[0].type.value == "IPV6"
    assert entities[0].value == "fe80::1"


def test_addresses_that_identify_no_host_are_left_alone() -> None:
    # Loopback, the unspecified address, a netmask: there is nobody behind
    # them, and a log without its bind address is harder to read.
    assert d.find("listening on 0.0.0.0:8080 and 127.0.0.1, mask 255.255.255.0") == []
    assert d.find("listen tcp6 [::1]:0: bind: cannot assign") == []


def test_double_colons_in_code_and_markup_are_not_addresses() -> None:
    # All three parse as IPv6 addresses in space the IETF holds in reserve.
    assert d.find("would be::\n\n    response.headers") == []  # reStructuredText
    assert d.find("if sample[::2] == _null2 or sample[1::2] == _null2:") == []  # Python slices
    assert [e.value for e in d.find("CIDRs:[192.168.0.0/16 fd00:1::/120]")] == [
        "192.168.0.0",
        "fd00:1::",
    ]


def test_finds_ipv4_immediately_before_sentence_period() -> None:
    entities = d.find("The affected host is 228.181.198.80. Please check it.")
    assert [e.value for e in entities] == ["228.181.198.80"]


def test_does_not_match_prefix_of_longer_dotted_sequence() -> None:
    assert d.find("version 1.2.3.4.5 released") == []


def test_ignores_plain_version_number() -> None:
    # "1.2.3" alone has only 3 octets: not a valid IPv4.
    assert d.find("release 1.2.3") == []


def test_finds_both_versions_in_one_text() -> None:
    assert types("v4 192.168.0.1 and v6 fe80::1") == ["IPV4", "IPV6"]


def test_a_version_labelled_dotted_quad_is_not_an_address() -> None:
    assert types("upgraded to version 10.2.14.3, v2.4.1.0 and build 1.0.0.7") == []
    assert types("firmware: 3.1.0.2 installed") == []
    # Unlabelled, or labelled as a host, it is still an address.
    assert types("server 10.2.14.3 is down") == ["IPV4"]
    assert types("ssh to 192.168.1.20 (version check failed)") == ["IPV4"]


def test_product_and_package_versions_are_not_addresses() -> None:
    # A reduced Chrome user-agent string, and a Windows package identity
    # from a real update log: 541 of these were masked in one 2,000-line file.
    assert d.find("AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36") == []
    assert (
        d.find("Package_for_KB2952664~31bf3856ad364e35~amd64~~6.1.1.3, ApplicableState: 112") == []
    )
    assert [
        e.value
        for e in d.find("NameNode address change detected. Old: msra-sa-41/10.190.173.170:9000")
    ] == ["10.190.173.170"]
