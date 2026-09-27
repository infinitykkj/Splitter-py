"""Split files into fixed-size raw chunks and generate manifest."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from xml.sax.saxutils import escape

try:
    from .constants import DEFAULT_BUFFER_SIZE, DEFAULT_PART_SIZE
    from .io_utils import copy_exact_bytes, sha1_of_file
    from .manifest import Manifest, PartMeta
except ImportError:  # pragma: no cover - standalone script compatibility
    from constants import DEFAULT_BUFFER_SIZE, DEFAULT_PART_SIZE
    from io_utils import copy_exact_bytes, sha1_of_file
    from manifest import Manifest, PartMeta

# <prefix>_<index>.pkg / <prefix>-<index>.pkg / <prefix><index>.pkg
SPLIT_PKG_NAME_RE = re.compile(r"^(?P<prefix>.+?)[_-]?(?P<index>\d+)\.pkg$", re.IGNORECASE)

# Hard ceiling for a single metadata range read. Retail PKG entry tables and
# param.sfo files are a few KiB; anything beyond this is pathological and must
# never be materialised in RAM (a bogus entry_count would otherwise slurp a
# whole 1.9 GiB part plus one dict per entry).
MAX_METADATA_READ_BYTES = 16 * 1024 * 1024


class LocalPKGMetadataExtractor:
    """Extrator de metadados de PKG local (sem HTTP)"""

    PKG_MAGIC = b'\x7FCNT'
    PKG_HEADER_SIZE = 0x5A0
    PKG_TABLE_ENTRY_SIZE = 0x20
    PKG_CONTENT_ID_SIZE = 0x30

    def __init__(self, file_path: str, verbose: bool = False):
        self.file_path = Path(file_path)
        self.verbose = verbose
        self._file = None

    def log(self, message: str, level: str = "INFO"):
        if self.verbose or level == "ERROR":
            prefix = {"INFO": "[INFO]", "SUCCESS": "[OK]", "ERROR": "[ERROR]", "WARN": "[WARN]", "DEBUG": "[DEBUG]"}.get(level, "[*]")
            print(f"{prefix} {message}")

    def _open(self):
        self._file = open(self.file_path, 'rb')

    def _close(self):
        if self._file:
            self._file.close()
            self._file = None

    def _read_range(self, start: int, end: int) -> bytes:
        length = end - start + 1
        if length <= 0:
            return b""
        if length > MAX_METADATA_READ_BYTES:
            raise ValueError(
                f"metadata range too large: {length} bytes "
                f"(limit {MAX_METADATA_READ_BYTES})"
            )
        if not self._file:
            self._open()
        self._file.seek(start)
        return self._file.read(length)

    def extract_package_digest(self) -> str:
        """Return the uppercase SHA-256 header digest (0xFE0..0x10FF).

        Only ~1.7 KiB of the PKG header is touched: the entry table and
        param.sfo are never read, so memory stays constant no matter how
        large (or bogus) ``entry_count`` is.
        """
        try:
            self._parse_header(self._read_range(0, self.PKG_HEADER_SIZE - 1))
            digest_sig_data = self._read_range(0xFE0, 0x10FF)
            if len(digest_sig_data) < 32:
                raise ValueError("PKG header digest truncated")
            return digest_sig_data[0:32].hex().upper()
        finally:
            self._close()

    def extract_metadata(self) -> dict:
        """Extrai metadados completos do PKG local"""
        try:
            self.log("Iniciando extração de metadados do PKG local...", "INFO")

            header_data = self._read_range(0, self.PKG_HEADER_SIZE - 1)
            header = self._parse_header(header_data)

            digest_sig_data = self._read_range(0xFE0, 0x10FF)
            header['header_digest'] = digest_sig_data[0:32].hex().upper()
            header['header_signature'] = digest_sig_data[32:].hex().upper()

            entries = self._read_entry_table(header)
            header['entries'] = entries

            param_sfo_entry = next((e for e in entries if e['id'] == 0x1000), None)
            if param_sfo_entry:
                sfo_params = self._read_param_sfo_from_entry(header, param_sfo_entry)
                header['params'] = sfo_params
                header['title'] = sfo_params.get('TITLE', '')
                header['title_id'] = sfo_params.get('TITLE_ID', '')
                header['category'] = sfo_params.get('CATEGORY', '')
                self.log(f"Title: {header['title']}", "SUCCESS")

            self.log("Extração concluída!", "SUCCESS")
            return header

        finally:
            self._close()

    def _parse_header(self, data: bytes) -> dict:
        header = {}

        magic = data[0:4]
        if magic != self.PKG_MAGIC:
            raise Exception(f"Invalid PKG magic: {magic.hex()}")

        header['magic'] = magic.decode('ascii', errors='ignore')
        header['flags'] = struct.unpack('>I', data[0x04:0x08])[0]
        header['entry_count'] = struct.unpack('>I', data[0x10:0x14])[0]
        header['entry_table_offset'] = struct.unpack('>I', data[0x18:0x1C])[0]
        header['main_ent_data_size'] = struct.unpack('>I', data[0x1C:0x20])[0]
        header['body_offset'] = struct.unpack('>Q', data[0x20:0x28])[0]
        header['body_size'] = struct.unpack('>Q', data[0x28:0x30])[0]

        content_id_bytes = data[0x40:0x40 + self.PKG_CONTENT_ID_SIZE]
        header['content_id'] = content_id_bytes.decode('ascii', errors='ignore').rstrip('\x00')

        header['drm_type'] = struct.unpack('>I', data[0x70:0x74])[0]
        header['content_type'] = struct.unpack('>I', data[0x74:0x78])[0]
        header['package_size'] = struct.unpack('>Q', data[0x430:0x438])[0]

        self.log(f"Package Size: {header['package_size']} bytes", "DEBUG")
        self.log(f"Content ID: {header['content_id']}", "DEBUG")

        return header

    def _read_entry_table(self, header: dict) -> list:
        table_offset = header['entry_table_offset']
        table_size = header['entry_count'] * self.PKG_TABLE_ENTRY_SIZE

        if table_size > MAX_METADATA_READ_BYTES:
            raise ValueError(
                f"PKG entry table too large: {table_size} bytes "
                f"(entry_count={header['entry_count']})"
            )

        entry_data = self._read_range(table_offset, table_offset + table_size - 1)

        entries = []
        for i in range(header['entry_count']):
            offset = i * self.PKG_TABLE_ENTRY_SIZE
            entry_bytes = entry_data[offset:offset + self.PKG_TABLE_ENTRY_SIZE]

            entry = {
                'id': struct.unpack('>I', entry_bytes[0x00:0x04])[0],
                'filename_offset': struct.unpack('>I', entry_bytes[0x04:0x08])[0],
                'flags1': struct.unpack('>I', entry_bytes[0x08:0x0C])[0],
                'flags2': struct.unpack('>I', entry_bytes[0x0C:0x10])[0],
                'data_offset': struct.unpack('>I', entry_bytes[0x10:0x14])[0],
                'data_size': struct.unpack('>I', entry_bytes[0x14:0x18])[0],
            }
            entries.append(entry)

        return entries

    def _read_param_sfo_from_entry(self, header: dict, entry: dict) -> dict:
        sfo_offset = entry['data_offset']
        sfo_size = entry['data_size']

        sfo_data = self._read_range(sfo_offset, sfo_offset + sfo_size - 1)

        if sfo_data[0:4] != b'\x00PSF':
            raise Exception(f"Invalid SFO magic: {sfo_data[0:4].hex()}")

        key_table_offset = struct.unpack('<I', sfo_data[8:12])[0]
        data_table_offset = struct.unpack('<I', sfo_data[12:16])[0]
        tables_entries = struct.unpack('<I', sfo_data[16:20])[0]

        params = {}
        for i in range(tables_entries):
            entry_offset = 20 + (i * 16)
            entry_bytes = sfo_data[entry_offset:entry_offset + 16]

            key_offset = struct.unpack('<H', entry_bytes[0:2])[0]
            param_fmt = struct.unpack('<H', entry_bytes[2:4])[0]
            param_len = struct.unpack('<I', entry_bytes[4:8])[0]
            data_offset_rel = struct.unpack('<I', entry_bytes[12:16])[0]

            key_start = key_table_offset + key_offset
            key_end = sfo_data.index(b'\x00', key_start)
            key_name = sfo_data[key_start:key_end].decode('ascii')

            value_start = data_table_offset + data_offset_rel

            if param_fmt == 0x0004:
                value_end = sfo_data.index(b'\x00', value_start)
                value = sfo_data[value_start:value_end].decode('utf-8', errors='ignore')
            elif param_fmt == 0x0404:
                value = struct.unpack('<I', sfo_data[value_start:value_start + 4])[0]
            else:
                value_bytes = sfo_data[value_start:value_start + param_len]
                value = value_bytes.decode('utf-8', errors='ignore').rstrip('\x00')

            params[key_name] = value

        return params


def build_ps4_manifest(
    file_size: int,
    package_digest: str | None,
    pieces: list[dict],
) -> dict:
    """Build the official PS4 manifest document."""
    return {
        "originalFileSize": file_size,
        "packageDigest": package_digest or "",
        "numberOfSplitFiles": len(pieces),
        "pieces": pieces,
    }


def generate_ps4_manifests(
    directory: str = ".",
    base_url: str | None = None,
    output_dir: str | None = None,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    no_hash: bool = False,
) -> list[Path]:
    """Generate PS4 manifests from already-split ``<prefix>_<index>.pkg`` files.

    Scans *directory* for files named like ``GAME_0.pkg``, ``GAME_1.pkg``, ...
    and writes one official PS4 manifest per prefix group
    (``<prefix>.manifest.json``) without writing any part files.

    Pieces are ordered by the numeric index, ``fileOffset`` accumulates,
    ``hashValue`` is the uppercase SHA-1 of each part and ``packageDigest``
    comes from the PKG header of the first part (same extractor used by
    ``split_file``).

    With ``no_hash=True`` nothing is hashed: ``packageDigest`` and every
    ``hashValue`` are written as empty strings.

    Returns the list of generated manifest paths.
    """
    if not base_url:
        raise ValueError("base_url is required for PS4 manifest generation")
    if buffer_size <= 0:
        raise ValueError("buffer_size must be > 0")

    src_dir = Path(directory).resolve()
    if not src_dir.is_dir():
        raise NotADirectoryError(f"directory not found: {src_dir}")

    out_dir = Path(output_dir).resolve() if output_dir else src_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[tuple[int, Path]]] = {}
    for path in sorted(src_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".pkg":
            continue
        match = SPLIT_PKG_NAME_RE.match(path.name)
        if not match:
            print(f"[WARN] Ignorado (padrao <prefixo>_<indice>.pkg esperado): {path.name}")
            continue
        groups.setdefault(match.group("prefix"), []).append(
            (int(match.group("index")), path)
        )

    if not groups:
        raise ValueError(f"no <prefix>_<index>.pkg files found in {src_dir}")

    manifest_paths: list[Path] = []
    hash_buffer = bytearray(buffer_size) if not no_hash else None
    for prefix in sorted(groups):
        entries = sorted(groups[prefix], key=lambda item: item[0])
        indexes = [index for index, _ in entries]
        if len(set(indexes)) != len(indexes):
            raise ValueError(f"duplicate part index in group '{prefix}': {indexes}")
        missing = sorted(set(range(indexes[-1] + 1)) - set(indexes))
        if missing:
            print(f"[WARN] Grupo '{prefix}': indices ausentes {missing}")

        print(f"[INFO] Grupo '{prefix}': {len(entries)} arquivo(s)")

        package_digest = ""
        if not no_hash:
            package_digest = LocalPKGMetadataExtractor(
                str(entries[0][1]), verbose=False
            ).extract_package_digest()

        pieces: list[dict] = []
        offset = 0
        for index, path in entries:
            size = path.stat().st_size
            pieces.append(
                {
                    "url": f"{base_url.rstrip('/')}/{path.name}",
                    "fileOffset": offset,
                    "fileSize": size,
                    "hashValue": ""
                    if no_hash
                    else sha1_of_file(str(path), buffer_size, hash_buffer).upper(),
                }
            )
            offset += size

        manifest_path = out_dir / f"{prefix}.manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(
                build_ps4_manifest(offset, package_digest, pieces),
                fh,
                indent=2,
            )
        print(f"[OK] Manifesto PS4 salvo: {manifest_path}")
        manifest_paths.append(manifest_path)

    return manifest_paths


def split_file(
    input_path: str,
    output_dir: str | None = None,
    part_size: int = DEFAULT_PART_SIZE,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    include_hashes: bool = False,
    base_url: str | None = None,
    is_pkg: bool = False,
    is_ps3: bool = False,
    no_hash: bool = False,
) -> Path:
    """Split a file and create a manifest.

    Output format depends on the mode:
    - default: JSON manifest (``Manifest``)
    - ``is_pkg=True``: PS4-style JSON manifest (requires ``base_url``)
    - ``is_ps3=True``: PS3 ``hfs_manifest`` XML (requires ``base_url``)

    With ``no_hash=True`` no digest is computed: ``packageDigest`` comes
    out empty and every ``hashValue``/``sha256`` field is omitted.

    Returns the manifest path.
    """
    def log(msg: str, level: str = "INFO"):
        if is_pkg or is_ps3 or level == "ERROR":
            prefix = {"INFO": "[INFO]", "SUCCESS": "[OK]", "ERROR": "[ERROR]", "WARN": "[WARN]"}.get(level, "[*]")
            print(f"{prefix} {msg}")

    if part_size <= 0:
        raise ValueError("part_size must be > 0")
    if buffer_size <= 0:
        raise ValueError("buffer_size must be > 0")
    if is_pkg and is_ps3:
        raise ValueError("--pkg and --ps3 are mutually exclusive")
    if is_ps3 and not base_url:
        raise ValueError("base_url is required for PS3 (hfs_manifest) output")

    if no_hash:
        include_hashes = False

    source = Path(input_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"input file not found: {source}")

    out_dir = Path(output_dir).resolve() if output_dir else source.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    file_size = source.stat().st_size
    base_name = source.name

    parts: list[PartMeta] = []
    offset = 0
    part_index = 0
    global_hash = hashlib.sha256() if include_hashes else None

    expected_parts = (file_size + part_size - 1) // part_size if file_size else 0
    if is_ps3:
        index_digits = max(2, len(str(expected_parts)))

    with source.open("rb") as src:
        while offset < file_size:
            target = min(part_size, file_size - offset)
            if is_ps3:
                part_name = f"{source.stem}_{part_index:0{index_digits}d}{source.suffix}"
            else:
                part_name = f"{base_name}.part{part_index}"
            part_path = out_dir / part_name

            part_hash = hashlib.sha256() if include_hashes else None
            part_sha1 = hashlib.sha1() if is_pkg and not no_hash else None
            hashers = tuple(h for h in (part_hash, part_sha1, global_hash) if h is not None)

            with part_path.open("wb") as dst:
                copied = copy_exact_bytes(
                    src=src,
                    dst=dst,
                    target_bytes=target,
                    buffer_size=buffer_size,
                    hashers=hashers,
                )

            if copied != target:
                raise IOError(
                    f"unexpected EOF while writing {part_name}: expected {target}, got {copied}"
                )

            start = offset
            end = offset + copied - 1
            offset += copied

            sha1_value = part_sha1.hexdigest() if part_sha1 else None

            if (is_pkg or is_ps3) and base_url:
                part_url = f"{base_url.rstrip('/')}/{part_name}"
            else:
                part_url = None

            parts.append(
                PartMeta(
                    part=part_index,
                    file=part_name,
                    start=start,
                    end=end,
                    size=copied,
                    sha256=part_hash.hexdigest() if part_hash is not None else None,
                    sha1=sha1_value,
                    url=part_url,
                )
            )
            part_index += 1

    package_digest = ""
    if is_pkg and not no_hash:
        log("Extraindo metadados do PKG...", "INFO")
        pkg_extractor = LocalPKGMetadataExtractor(str(source), verbose=False)
        package_digest = pkg_extractor.extract_package_digest()

    if is_pkg and base_url:
        pieces = [
            {
                "url": part.url,
                "fileOffset": part.start,
                "fileSize": part.size,
                "hashValue": part.sha1.upper() if part.sha1 else "",
            }
            for part in parts
        ]
        manifest_data = build_ps4_manifest(file_size, package_digest, pieces)

        manifest_path = out_dir / f"{base_name}.manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, indent=2)
        log(f"Manifesto PS4 salvo: {manifest_path}", "SUCCESS")
    elif is_ps3:
        manifest_lines = [
            "<hfs_manifest>",
            f"<file_name>{escape(base_name)}</file_name>",
            f"<file_size>{file_size}</file_size>",
            f"<number_of_split_files>{len(parts)}</number_of_split_files>",
        ]
        for part in parts:
            manifest_lines.append(
                f'<pieces file_size="{part.size}" index="{part.part}" '
                f'url="{escape(part.url or "")}"/>'
            )
        manifest_lines.append("</hfs_manifest>")
        manifest_path = out_dir / f"{base_name}.manifest.xml"
        manifest_path.write_text(
            "\n".join(manifest_lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        log(f"Manifesto PS3 salvo: {manifest_path}", "SUCCESS")
    else:
        manifest = Manifest(
            file_name=base_name,
            file_size=file_size,
            chunk_size=part_size,
            parts=parts,
            sha256=global_hash.hexdigest() if global_hash is not None else None,
        )
        manifest_path = out_dir / f"{base_name}.manifest.json"
        manifest.save(manifest_path)

    return manifest_path


if __name__ == "__main__":
    try:
        from .cli import main
    except ImportError:  # pragma: no cover - standalone script compatibility
        from cli import main

    raise SystemExit(main())
