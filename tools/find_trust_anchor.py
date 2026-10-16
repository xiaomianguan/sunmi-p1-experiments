#!/usr/bin/env python3
"""Decide whether LK trusts the *embedded* signing cert or a compiled-in anchor.

If the trust anchor (a cert, a public key, or a hash of either) is stored inside
LK / preloader / secro, then signing our own images is impossible and LK must be
patched. If nothing is stored anywhere, LK is very likely verifying against the
certificate that ships with each image -- which would mean we can sign our own.

Searches for:
  * SHA256/SHA1 of the cert DER, the public key DER, the modulus, the exponent
  * the cert DER itself and its distinguishing byte runs
  * the sha256WithRSA OID
  * the SHA-256 IV and round constants (to locate the crypto code in LK)
"""
import hashlib
import sys

from cryptography import x509
from cryptography.hazmat.primitives import serialization

BOOT = "dumps/boot.bin"
SIG_OFF = 0x76F800

boot = open(BOOT, "rb").read()
blob = boot[SIG_OFF:]
olen = int.from_bytes(blob[2:4], "big")
p = 6 + int.from_bytes(blob[5:6], "big")
clen = int.from_bytes(blob[p + 2:p + 4], "big")
cert_der = blob[p:p + 4 + clen]
cert = x509.load_der_x509_certificate(cert_der)
pub = cert.public_key()
pub_der = pub.public_bytes(serialization.Encoding.DER,
                           serialization.PublicFormat.SubjectPublicKeyInfo)
numbers = pub.public_numbers()
modulus = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")

needles = {
    "sha256(cert_der)": hashlib.sha256(cert_der).digest(),
    "sha1(cert_der)": hashlib.sha1(cert_der).digest(),
    "sha256(pubkey_der)": hashlib.sha256(pub_der).digest(),
    "sha1(pubkey_der)": hashlib.sha1(pub_der).digest(),
    "sha256(modulus)": hashlib.sha256(modulus).digest(),
    "sha1(modulus)": hashlib.sha1(modulus).digest(),
    "cert_der[:64]": cert_der[:64],
    "cert_der[-64:]": cert_der[-64:],
    "pubkey_der[:64]": pub_der[:64],
    "modulus[:32]": modulus[:32],
    "modulus[-32:]": modulus[-32:],
    "sha256WithRSA OID": bytes.fromhex("06092a864886f70d01010b"),
    "email in cert": b"766018769@qq.com",
    "CN=fym": b"fym",
}
# SHA-256 IV / round constants (little-endian words)
sha256_iv = b"".join(x.to_bytes(4, "little") for x in
                     (0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a))
sha256_k = b"".join(x.to_bytes(4, "little") for x in
                    (0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5))
needles["sha256 IV (LE)"] = sha256_iv
needles["sha256 K0-3 (LE)"] = sha256_k

print(f"cert        : {len(cert_der)} bytes, RSA {pub.key_size}")
print(f"pubkey DER  : {len(pub_der)} bytes, modulus {len(modulus)} bytes")
print()

targets = [
    "dumps/lk.bin",
    "dumps/preloader_boot1.bin",
    "dumps/preloader_raw.bin",
    "dumps/secro.bin",
    "dumps/proinfo.bin",
    "dumps/nvram.bin",
    "dumps/oemkeystore.bin",
    "dumps/keystore.bin",
]
for t in targets:
    try:
        d = open(t, "rb").read()
    except FileNotFoundError:
        print(f"{t:32} (missing)")
        continue
    found = []
    for name, pat in needles.items():
        i = d.find(pat)
        if i >= 0:
            found.append(f"{name}@0x{i:x}")
    print(f"{t:32} {'FOUND: ' + ', '.join(found) if found else 'none of the needles present'}")
