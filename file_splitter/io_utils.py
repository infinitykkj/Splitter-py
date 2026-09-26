"""Low-level I/O helpers optimized for streaming binary files."""

from __future__ import annotations

import hashlib
from typing import BinaryIO


def copy_exact_bytes(
    src: BinaryIO,
    dst: BinaryIO,
    target_bytes: int,
    buffer_size: int,
    hashers: tuple[hashlib._Hash, ...] = (),
) -> int:
    """Copy exactly up to target_bytes from src to dst.

    Returns the amount of bytes actually copied.
    """
    if target_bytes < 0:
        raise ValueError("target_bytes must be >= 0")
    if buffer_size <= 0:
        raise ValueError("buffer_size must be > 0")

    copied = 0
    buffer = bytearray(buffer_size)
    view = memoryview(buffer)

    while copied < target_bytes:
        remaining = target_bytes - copied
        read_len = buffer_size if remaining > buffer_size else remaining
        read_n = src.readinto(view[:read_len])

        if not read_n:
            break

        chunk = view[:read_n]
        dst.write(chunk)
        for hasher in hashers:
            hasher.update(chunk)
        copied += read_n

    return copied


def _hash_of_file(path: str, algorithm: str, buffer_size: int) -> str:
    digest = hashlib.new(algorithm)
    with open(path, "rb") as fh:
        buffer = bytearray(buffer_size)
        view = memoryview(buffer)
        while True:
            read_n = fh.readinto(view)
            if not read_n:
                break
            digest.update(view[:read_n])
    return digest.hexdigest()


def sha1_of_file(path: str, buffer_size: int) -> str:
    """Compute SHA-1 hash for a file by streaming bytes."""
    return _hash_of_file(path, "sha1", buffer_size)


def sha256_of_file(path: str, buffer_size: int) -> str:
    """Compute SHA-256 hash for a file by streaming bytes."""
    return _hash_of_file(path, "sha256", buffer_size)
