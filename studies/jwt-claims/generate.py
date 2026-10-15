"""Generate synthetic JWTs with real encoders, retaining only public asymmetric keys.

No token is issued by a service or sent to an identity provider. RSA/EC signatures
change when regenerated; replay uses the retained, hash-recorded fixture bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

HERE = Path(__file__).resolve().parent
HMAC_KEY = "synthetic-test-only-signing-material-" * 4


def main() -> None:
    claims = {
        "sub": "customer-1042",
        "email": "alice@example.org",
        "name": "Alice Example",
        "exp": 2_000_000_000,
    }
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ec_key = ec.generate_private_key(ec.SECP256R1())
    ed_key = ed25519.Ed25519PrivateKey.generate()
    rows = []

    def add(
        name: str, algorithm: str, key: object, payload: dict, headers: dict | None = None
    ) -> None:
        token = jwt.encode(payload, key, algorithm=algorithm, headers=headers)
        public = (
            key.public_key()
            .public_bytes(  # type: ignore[attr-defined]
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
            if not isinstance(key, str)
            else key
        )
        options = {"verify_exp": False, "verify_signature": algorithm != "none"}
        assert jwt.decode(token, public, algorithms=[algorithm], options=options) == payload
        rows.append(
            {
                "id": name,
                "algorithm": algorithm,
                "token": token,
                "verificationKey": public,
                "claims": payload,
                "claimsSha256": hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
                "oracle": "PyJWT signature verification"
                if algorithm != "none"
                else "PyJWT decode only; unsecured JWT",
            }
        )

    for algorithm in ("HS256", "HS384", "HS512"):
        add(algorithm.lower(), algorithm, HMAC_KEY, claims)
    for algorithm, key in (
        ("RS256", rsa_key),
        ("PS256", rsa_key),
        ("ES256", ec_key),
        ("EdDSA", ed_key),
    ):
        add(algorithm.lower(), algorithm, key, claims)
    add("unsecured", "none", "", claims)
    add("no-typ", "HS256", HMAC_KEY, claims, {"typ": None})
    add(
        "unicode-claims",
        "HS256",
        HMAC_KEY,
        {**claims, "name": "架空の利用者", "email": "利用者@例え.テスト"},
    )
    add(
        "long-claims",
        "HS256",
        HMAC_KEY,
        {**claims, "notes": "Synthetic private case notes. " * 100},
    )
    add(
        "header-url",
        "HS256",
        HMAC_KEY,
        claims,
        {"kid": "synthetic-key-id", "jku": "https://example.invalid/keys"},
    )
    output = {
        "provenance": "Synthetic claims and locally generated signatures; not issued credentials. Asymmetric private keys are discarded.",
        "encoder": f"PyJWT {jwt.__version__}",
        "cases": rows,
    }
    (HERE / "cases.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"Generated and independently decoded/verified {len(rows)} retained JWT fixtures")


if __name__ == "__main__":
    main()
