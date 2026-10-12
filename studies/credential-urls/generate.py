"""Generate synthetic signed URLs offline with the real cloud SDKs.

Install requirements.txt in a separate environment, then run this file.
No cloud account, ambient credentials, or HTTP transport is used. The RSA key
is generated in memory and discarded. Regeneration changes RSA signatures;
the retained cases.json is the exact input to the before/after replay.
"""

from __future__ import annotations

import base64
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import boto3
from azure.storage.blob import (
    AccountSasPermissions,
    BlobSasPermissions,
    ResourceTypes,
    generate_account_sas,
    generate_blob_sas,
)
from botocore.config import Config
from botocore.signers import CloudFrontSigner
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from google.auth.crypt import RSASigner
from google.cloud import storage
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent
NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
EXPIRY = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
rows: list[dict[str, object]] = []


def add(name: str, url: str, origin: str, mask: bool = True) -> None:
    rows.append({"id": name, "url": url, "origin": origin, "mask": mask})


def no_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("Fixture generation attempted network access")


with (
    patch("socket.socket.connect", no_network),
    patch("socket.getaddrinfo", no_network),
    patch("botocore.auth.get_current_datetime", return_value=NOW.replace(tzinfo=None)),
    patch("botocore.auth.time.time", return_value=NOW.timestamp()),
    patch("google.cloud.storage._signing._NOW", return_value=NOW),
):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    credentials = Credentials(
        RSASigner.from_string(pem),
        "fixture@example.invalid",
        "https://oauth.example.invalid/token",
    )
    gcs = storage.Client(project="veil-synthetic", credentials=credentials)
    blob = gcs.bucket("veil-synthetic").blob("private.txt")
    for version in ("v4", "v2"):
        add(
            f"gcs-{version}",
            blob.generate_signed_url(version=version, expiration=EXPIRY, method="GET"),
            f"google-cloud-storage Blob.generate_signed_url {version}",
        )
    for version in ("s3v4", "s3"):
        s3 = boto3.client(
            "s3",
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="synthetic-key-with-no-account",
            region_name="us-east-1",
            config=Config(signature_version=version),
        )
        add(
            f"aws-{version}",
            s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": "veil-synthetic", "Key": "private.txt"},
                ExpiresIn=86400,
            ),
            f"boto3 S3.generate_presigned_url {version}",
        )
        s3.close()
    key = base64.b64encode(b"synthetic-account-key-with-no-account").decode()
    for name, token in (
        (
            "blob",
            generate_blob_sas(
                "veilsynthetic",
                "private",
                "file.txt",
                account_key=key,
                permission=BlobSasPermissions(read=True),
                start=NOW,
                expiry=EXPIRY,
            ),
        ),
        (
            "account",
            generate_account_sas(
                "veilsynthetic",
                key,
                resource_types=ResourceTypes(object=True),
                permission=AccountSasPermissions(read=True),
                start=NOW,
                expiry=EXPIRY,
            ),
        ),
        (
            "stored-policy",
            generate_blob_sas(
                "veilsynthetic",
                "private",
                "file.txt",
                account_key=key,
                policy_id="synthetic",
            ),
        ),
    ):
        add(
            f"azure-{name}",
            f"https://veilsynthetic.blob.core.windows.net/private/file.txt?{token}",
            f"azure-storage-blob generate_{'account' if name == 'account' else 'blob'}_sas",
        )
    signer = CloudFrontSigner(
        "K_SYNTHETIC",
        lambda message: private.sign(message, padding.PKCS1v15(), hashes.SHA1()),
    )
    resource = "https://cdn.example.invalid/private.txt"
    add(
        "cloudfront-canned",
        signer.generate_presigned_url(resource, date_less_than=EXPIRY),
        "botocore CloudFrontSigner canned policy",
    )
    add(
        "cloudfront-custom",
        signer.generate_presigned_url(
            resource, policy=signer.build_policy(resource, date_less_than=EXPIRY)
        ),
        "botocore CloudFrontSigner custom policy",
    )
    gcs.close()

# Explicit cases distinguish name decoding, component boundaries, and generic
# non-credential signatures from supported access-bearing formats.
for name, tail, sensitive in (
    ("oauth-fragment", "callback#access_token=short-secret&token_type=Bearer", True),
    ("oauth-fragment-second", "callback#state=ok&access_token=short-secret", True),
    ("encoded-name", "?access%5Ftoken=short-secret", True),
    ("encoded-fragment-name", "#access%5Ftoken=short-secret", True),
    ("router-fragment", "#/callback?access%5Ftoken=short-secret", True),
    ("mixed-case", "?AcCeSs_ToKeN=short-secret", True),
    ("duplicate-name", "?access_token=&access_token=short-secret", True),
    ("query-userinfo-control", "?token=short-secret", True),
    ("encoded-azure-name", "?s%76=2026&%73ig=short-secret", True),
    ("signature-first", "?Signature=short-secret&Key-Pair-Id=synthetic", True),
    ("azure-custom-domain", "?sig=short-secret&sv=2026", True),
    ("gcs-custom-domain", "?X-Goog-Signature=short-secret", True),
    ("aws-custom-domain", "?X-Amz-Signature=short-secret", True),
    ("legacy-router-fragment", "#/callback?token=short-secret", True),
    ("ordinary-url", "guide?topic=privacy#examples", False),
    ("generic-sig", "?sig=short-value", False),
    ("generic-signature", "?signature=short-value", False),
    ("empty-token", "?access_token=", False),
    ("empty-fragment-token", "#access_token=", False),
    ("empty-azure-signature", "?sv=2026&sig=", False),
    ("empty-azure-version", "?sv=&sig=short-value", False),
    ("empty-v4-signature", "?X-Goog-Signature=", False),
    ("empty-signer", "?Signature=short-value&Key-Pair-Id=", False),
    ("similar-name", "?not_access_token=short-value", False),
    ("double-encoded-name", "?access%255Ftoken=short-value", False),
    ("encoded-value", "?note=access_token%3Dshort-value", False),
    ("encoded-separator", "?note=x%26access_token%3Dshort-value", False),
    ("separate-components", "?sv=2026#sig=short-value", False),
    ("path-only", "access_token=short-value", False),
    ("userinfo", "postgres://user:short-secret@database/app", True),
):
    url = tail if "://" in tail else f"https://example.invalid/{tail}"
    add(name, url, "handwritten syntax control", sensitive)

report = {
    "synthetic": True,
    "network": "socket connect and DNS blocked during generation",
    "signingTime": NOW.isoformat(),
    "packages": {
        name: importlib.metadata.version(name)
        for name in (
            "google-cloud-storage",
            "google-auth",
            "azure-storage-blob",
            "boto3",
            "botocore",
            "cryptography",
        )
    },
    "cases": rows,
}
(ROOT / "cases.json").write_text(json.dumps(report, indent=2) + "\n")
print(f"Generated {len(rows)} cases; {sum(bool(r['mask']) for r in rows)} credential URLs")
