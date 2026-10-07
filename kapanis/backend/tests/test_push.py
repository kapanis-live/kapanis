"""Web Push: the encryption is checked by decrypting as the browser would (RFC 8291), the signature by verifying it.
Run: .venv\Scripts\python -m unittest tests.test_push"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jwt  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: E402

import push  # noqa: E402


def browser_decrypt(body: bytes, key, auth: bytes) -> bytes:
    salt, (size,), n = body[:16], struct.unpack(">I", body[16:20]), body[20]
    sender_pub = body[21:21 + n]
    shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_pub))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + push._point(key) + sender_pub).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, body[21 + n:], None)
    assert size == 4096 and plain.endswith(b"\x02")
    return plain[:-1]


class PushCryptoTest(unittest.TestCase):
    def test_the_browser_can_read_what_the_server_encrypts(self):
        device = ec.generate_private_key(ec.SECP256R1())
        auth = b"0123456789abcdef"
        text = '{"baslik": "THYAO", "metin": "günlük kapanış 312,5 ₺"}'.encode()
        body = push.encrypt(text, push.b64(push._point(device)), push.b64(auth))
        self.assertEqual(browser_decrypt(body, device, auth), text)
        self.assertNotIn(b"THYAO", body)
        with self.assertRaises(Exception):                         # another device cannot read it
            browser_decrypt(body, ec.generate_private_key(ec.SECP256R1()), auth)

    def test_vapid_header_is_signed_for_the_push_service(self):
        k = push.new_keys()
        header = push.vapid_header("https://fcm.googleapis.com/fcm/send/abc", k, now=1_790_000_000)
        token = header.split("t=")[1].split(",")[0]
        self.assertTrue(header.startswith("vapid t=") and header.endswith("k=" + k["public"]))
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64(k["public"]))
        pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        claims = jwt.decode(token, pem, algorithms=["ES256"], audience="https://fcm.googleapis.com", options={"verify_exp": False})
        self.assertEqual(claims["exp"], 1_790_000_000 + 12 * 3600)
        self.assertTrue(claims["sub"].startswith("mailto:"))
        self.assertEqual(len(push.unb64(k["public"])), 65)


if __name__ == "__main__":
    unittest.main()
