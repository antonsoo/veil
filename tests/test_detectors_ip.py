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
    entities = d.find("host ::1 is up")
    assert len(entities) == 1


def test_ignores_plain_version_number() -> None:
    # "1.2.3" alone has only 3 octets: not a valid IPv4.
    assert d.find("release 1.2.3") == []


def test_finds_both_versions_in_one_text() -> None:
    assert types("v4 192.168.0.1 and v6 fe80::1") == ["IPV4", "IPV6"]
