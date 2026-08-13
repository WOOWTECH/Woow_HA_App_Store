"""AES-128-CBC encryption for Somfy PoE API."""
from __future__ import annotations

import logging
import secrets

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

_LOGGER = logging.getLogger(__name__)

BLOCK_SIZE = 16  # AES block size in bytes


class SomfyEncryption:
    """Handle AES-128-CBC encryption/decryption for Somfy protocol.

    Design Decisions:
    - Uses 'cryptography' library (recommended by HA, well-maintained)
    - Stateless design - no IV caching
    - Each encrypt() generates random IV
    - IV is prepended to ciphertext as per protocol
    """

    def __init__(self, key: str) -> None:
        """Initialize encryption with hex key string.

        Args:
            key: 32-character hex string (16 bytes)

        Raises:
            ValueError: If key format is invalid
        """
        if len(key) != 32 or not all(
            c in "0123456789ABCDEFabcdef" for c in key
        ):
            raise ValueError("Key must be 32-character hex string")

        self._key_bytes = bytes.fromhex(key)
        if len(self._key_bytes) != 16:
            raise ValueError("Key must be 16 bytes (128 bits)")

        _LOGGER.debug("Initialized encryption with 128-bit AES-CBC key")

    def encrypt(self, plaintext: str, use_zero_padding: bool = True) -> bytes:
        """Encrypt plaintext with random IV.

        Args:
            plaintext: UTF-8 string to encrypt
            use_zero_padding: If True, use zero-padding (100% success rate).
                            If False, use PKCS7 padding (80% success rate).

        Returns:
            IV (16 bytes) + ciphertext with padding
        """
        # Generate random IV for each message
        iv = secrets.token_bytes(BLOCK_SIZE)
        _LOGGER.debug("Generated IV: %s", iv.hex())

        # Pad plaintext to block size
        plaintext_bytes = plaintext.encode("utf-8")
        if use_zero_padding:
            # Zero-padding: Tested 100% success rate
            padded = self._pad_zero(plaintext_bytes)
            _LOGGER.debug("Using zero-padding (100%% success rate)")
        else:
            # PKCS7 padding: Tested 80% success rate
            padded = self._pad_pkcs7(plaintext_bytes)
            _LOGGER.debug("Using PKCS7 padding (80%% success rate)")

        _LOGGER.debug(
            "Encryption: plaintext=%d bytes, padded=%d bytes",
            len(plaintext_bytes),
            len(padded)
        )

        # Encrypt
        cipher = Cipher(
            algorithms.AES(self._key_bytes), modes.CBC(iv), backend=default_backend()
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()

        _LOGGER.debug(
            "Encryption complete: IV=%s, ciphertext=%d bytes, total=%d bytes",
            iv.hex(),
            len(ciphertext),
            len(iv) + len(ciphertext)
        )

        # Return IV + ciphertext
        return iv + ciphertext

    def decrypt(self, data: bytes, use_zero_padding: bool = True) -> str:
        """Decrypt data with prepended IV.

        Args:
            data: IV (16 bytes) + ciphertext
            use_zero_padding: If True, expect zero-padding. If False, expect PKCS7.

        Returns:
            Decrypted UTF-8 string

        Raises:
            ValueError: If data is too short or padding invalid
        """
        if len(data) < BLOCK_SIZE + 1:
            raise ValueError("Data too short to contain IV and ciphertext")

        # Extract IV and ciphertext
        iv = data[:BLOCK_SIZE]
        ciphertext = data[BLOCK_SIZE:]
        _LOGGER.debug(
            "Decryption: IV=%s, ciphertext=%d bytes",
            iv.hex(),
            len(ciphertext)
        )

        # Decrypt
        cipher = Cipher(
            algorithms.AES(self._key_bytes), modes.CBC(iv), backend=default_backend()
        )
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        # Remove padding
        if use_zero_padding:
            plaintext = self._unpad_zero(padded_plaintext)
        else:
            plaintext = self._unpad_pkcs7(padded_plaintext)

        _LOGGER.debug(
            "Decryption complete: padded=%d bytes, unpadded=%d bytes",
            len(padded_plaintext),
            len(plaintext)
        )
        return plaintext.decode("utf-8")

    @staticmethod
    def _pad_zero(data: bytes) -> bytes:
        """Apply zero-padding (Somfy motor tested 100% success rate)."""
        padding_length = -len(data) % BLOCK_SIZE
        return data + b"\0" * padding_length

    @staticmethod
    def _unpad_zero(data: bytes) -> bytes:
        """Remove zero-padding."""
        return data.rstrip(b"\0")

    @staticmethod
    def _pad_pkcs7(data: bytes) -> bytes:
        """Apply PKCS7 padding."""
        padding_length = BLOCK_SIZE - (len(data) % BLOCK_SIZE)
        padding = bytes([padding_length] * padding_length)
        return data + padding

    @staticmethod
    def _unpad_pkcs7(data: bytes) -> bytes:
        """Remove PKCS7 padding.

        Raises:
            ValueError: If padding is invalid
        """
        if not data:
            raise ValueError("Cannot unpad empty data")

        padding_length = data[-1]
        if padding_length < 1 or padding_length > BLOCK_SIZE:
            raise ValueError(f"Invalid padding length: {padding_length}")

        _LOGGER.debug(
            "PKCS7 padding: length=%d, total_data=%d bytes",
            padding_length,
            len(data)
        )

        # Verify all padding bytes are correct
        padding = data[-padding_length:]
        if not all(b == padding_length for b in padding):
            raise ValueError("Invalid PKCS7 padding")

        return data[:-padding_length]
