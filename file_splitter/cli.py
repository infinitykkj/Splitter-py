"""CLI entrypoint for file splitter and merger."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

try:
    from .constants import DEFAULT_BUFFER_SIZE, DEFAULT_PART_SIZE
    from .manifest import Manifest
    from .merger import merge_file
    from .splitter import split_file
except ImportError:  # pragma: no cover - standalone script compatibility
    from constants import DEFAULT_BUFFER_SIZE, DEFAULT_PART_SIZE
    from manifest import Manifest
    from merger import merge_file
    from splitter import split_file


def _cmd_split(args: argparse.Namespace) -> int:
    manifest_path = split_file(
        input_path=args.input,
        output_dir=args.output_dir,
        part_size=args.part_size,
        buffer_size=args.buffer_size,
        include_hashes=args.with_hash,
        base_url=args.base_url,
        is_pkg=args.pkg,
        is_ps3=args.ps3,
    )
    print(f"Split concluido: {manifest_path}")
    return 0


def _cmd_merge(args: argparse.Namespace) -> int:
    output = merge_file(
        manifest_path=args.manifest,
        output_path=args.output,
        base_dir=args.parts_dir,
        buffer_size=args.buffer_size,
        verify_hashes=args.verify_hash,
    )
    print(f"Merge concluido: {output}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    manifest = Manifest.load(args.manifest)
    missing = []
    parts_dir = Path(args.parts_dir).resolve() if args.parts_dir else Path(args.manifest).resolve().parent

    for part in manifest.parts:
        part_path = parts_dir / part.file
        if not part_path.is_file():
            missing.append(str(part_path))

    print(f"Manifesto valido: {args.manifest}")
    print(f"Arquivo original: {manifest.file_name} ({manifest.file_size} bytes)")
    print(f"Quantidade de partes: {len(manifest.parts)}")
    if missing:
        print("Partes ausentes:")
        for path in missing:
            print(f"- {path}")
        return 2

    print("Todas as partes referenciadas existem no disco.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="file-splitter",
        description="Split and merge large files using raw byte ranges.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    split_parser = subparsers.add_parser("split", help="Split file into fixed-size parts")
    split_parser.add_argument("input", help="Input file path")
    split_parser.add_argument(
        "-o",
        "--output-dir",
        help="Directory for parts and manifest (default: input folder)",
    )
    split_parser.add_argument(
        "--part-size",
        type=int,
        default=DEFAULT_PART_SIZE,
        help=f"Part size in bytes (default: {DEFAULT_PART_SIZE})",
    )
    split_parser.add_argument(
        "--buffer-size",
        type=int,
        default=DEFAULT_BUFFER_SIZE,
        help=f"Streaming buffer in bytes (default: {DEFAULT_BUFFER_SIZE})",
    )
    split_parser.add_argument(
        "--with-hash",
        action="store_true",
        help="Include SHA-256 for each part and merged output",
    )
    mode_group = split_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--pkg",
        action="store_true",
        help="Treat input as PS4 PKG file, generate PS4-style JSON manifest",
    )
    mode_group.add_argument(
        "--ps3",
        action="store_true",
        help="Generate PS3 HFS manifest (hfs_manifest XML)",
    )
    split_parser.add_argument(
        "--base-url",
        help="Base URL for PS4/PS3 manifest pieces (e.g., https://host.com/download)",
    )
    split_parser.set_defaults(func=_cmd_split)

    merge_parser = subparsers.add_parser("merge", help="Merge parts from a manifest")
    merge_parser.add_argument("manifest", help="Manifest JSON path")
    merge_parser.add_argument("output", help="Reconstructed output file path")
    merge_parser.add_argument(
        "--parts-dir",
        help="Directory where part files are stored (default: manifest folder)",
    )
    merge_parser.add_argument(
        "--buffer-size",
        type=int,
        default=DEFAULT_BUFFER_SIZE,
        help=f"Streaming buffer in bytes (default: {DEFAULT_BUFFER_SIZE})",
    )
    merge_parser.add_argument(
        "--verify-hash",
        action="store_true",
        help="Validate part/full hashes if present in manifest",
    )
    merge_parser.set_defaults(func=_cmd_merge)

    validate_parser = subparsers.add_parser(
        "validate", help="Validate manifest schema, ranges, and part presence"
    )
    validate_parser.add_argument("manifest", help="Manifest JSON path")
    validate_parser.add_argument(
        "--parts-dir",
        help="Directory where part files are stored (default: manifest folder)",
    )
    validate_parser.set_defaults(func=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
