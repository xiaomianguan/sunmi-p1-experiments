#!/usr/bin/env python3
"""Analyse the MTK img_auth signature appended to boot.img.

Structure found:
    SEQUENCE {
        INTEGER :01                 # version
        SEQUENCE (969 bytes)        # X.509 certificate
        BIT STRING                  # RSA signature
    }

If we can reproduce the signed byte range we can (a) confirm the format and
(b) test whether LK trusts the *embedded* certificate (which would let us sign
our own images) or a trust anchor compiled into LK.
"""
import hashlib
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

BOOT = sys.argv[1] if len(sys.argv) > 1 else "dumps/boot.bin"
SIG_OFF = 0x76F800

boot = open(BOOT, "rb").read()
blob = boot[SIG_OFF:]
print(f"boot image      : {BOOT} ({len(boot)} bytes)")
print(f"signature blob  : offset 0x{SIG_OFF:x}")

# outer SEQUENCE
assert blob[0] == 0x30, "not a SEQUENCE"
olen = int.from_bytes(blob[2:4], "big")
print(f"blob            : SEQUENCE len={olen}")

# INTEGER
assert blob[4] == 0x02
vlen = blob[5]
version = int.from_bytes(blob[6:6 + vlen], "big")
print(f"version         : {version}")
p = 6 + vlen

# certificate
assert blob[p] == 0x30, "cert not a SEQUENCE"
clen = int.from_bytes(blob[p + 2:p + 4], "big")
cert_der = blob[p:p + 4 + clen]
print(f"certificate     : DER {len(cert_der)} bytes")
p += 4 + clen

cert = x509.load_der_x509_certificate(cert_der)
print(f"  subject       : {cert.subject.rfc4514_string()}")
print(f"  issuer        : {cert.issuer.rfc4514_string()}")
print(f"  self-signed   : {cert.subject == cert.issuer}")
print(f"  serial        : {cert.serial_number:x}")
print(f"  not before    : {cert.not_valid_before_utc}")
print(f"  not after     : {cert.not_valid_after_utc}")
pub = cert.public_key()
print(f"  key           : {type(pub).__name__} {pub.key_size} bits")
print(f"  sig alg       : {cert.signature_algorithm_oid.dotted_string}")

# signature: the blob is SEQUENCE { INTEGER, Certificate, SEQUENCE{ alg, BIT STRING } }
# The RSA signature is the trailing 256 bytes of the outer SEQUENCE.
end = 4 + olen
sig = blob[end - 256:end]
print(f"signature       : trailing {len(sig)} bytes of the blob")

# Candidate signed ranges -- try many offsets/lengths
print()
print("trying PKCS#1 v1.5 / SHA-256 over candidate ranges:")
hits = 0
cands = []
for end_off in (SIG_OFF, SIG_OFF, SIG_OFF):
    cands.append((f"boot[0:0x{end_off:x}]", boot[:end_off]))
cands.append(("boot[0:len]", boot))
cands.append(("boot[0x800:0x76f800] (after header)", boot[0x800:SIG_OFF]))
cands.append(("boot[0x800:0x76f800] page-aligned", boot[0x800:0x770000]))
for name, data in cands:
    try:
        pub.verify(sig, data, padding.PKCS1v15(), hashes.SHA256())
        print(f"  *** VERIFIED ***  {name}")
        hits += 1
    except Exception:
        print(f"  no match: {name}")

# Try verifying a bare digest (some schemes sign the hash directly)
from cryptography.hazmat.primitives.asymmetric import utils
for name, data in cands:
    d = hashlib.sha256(data).digest()
    try:
        pub.verify(sig, d, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
        print(f"  *** PREHASHED VERIFIED ***  {name}")
        hits += 1
    except Exception:
        pass

if not hits:
    print()
    print("No match yet. The signed blob may include a hash descriptor wrapper")
    print("(MTK img_auth signs a structure, not the raw image). Next step would be")
    print("to disassemble LK's sec_img_verify to see what it feeds the verifier.")

