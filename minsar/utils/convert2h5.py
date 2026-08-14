#!/usr/bin/env python3
"""Convert a MintPy-readable binary file (+ metadata) to HDF5 for view.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mintpy.utils import readfile, writefile

DESCRIPTION = """\
Convert between MintPy HDF5 and binary InSAR files (+ .rsc metadata).

Forward (default): binary + metadata -> HDF5 for view.py
Reverse (--reverse): HDF5 -> binary + .rsc
"""

EXAMPLE = """Examples:
convert2h5.py mask_unwrap
convert2h5.py /path/to/mask_unwrap -o /path/to/mask_unwrap.h5
convert2h5.py geo_velocity.unw --file-type velocity
convert2h5.py --reverse mask_unwrap.h5
convert2h5.py --reverse mask_unwrap.h5 -o mask_unwrap
"""

# ROI_PAC FILE_TYPE values with a leading dot -> MintPy HDF5 dataset names
FILE_TYPE_NORMALIZE = {
    ".msk": "mask",
    ".unw": "unwrapPhase",
    ".cor": "coherence",
    ".hgt": "height",
}
FILE_TYPE_DENORMALIZE = {value: key for key, value in FILE_TYPE_NORMALIZE.items()}


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE,
    )
    parser.add_argument(
        "infile",
        help="Input file (binary + .rsc forward; .h5 with --reverse)",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Convert HDF5 to binary + .rsc (default: binary -> HDF5)",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="outfile",
        default=None,
        help="Output path (default: <infile>.h5 forward; strip .h5 with --reverse)",
    )
    parser.add_argument(
        "--file-type",
        dest="file_type",
        default=None,
        help="Override FILE_TYPE metadata (forward: written to HDF5; reverse: written to .rsc)",
    )
    return parser


def _resolve_input(path: Path) -> Path:
    path = path.expanduser()
    if path.is_file():
        return path.resolve()

    if path.suffix.lower() == ".rsc" and path.with_suffix("").is_file():
        return path.with_suffix("").resolve()

    raise FileNotFoundError(f"input file not found: {path}")


def _default_outfile(infile: Path) -> Path:
    return infile.with_suffix(".h5")


def _default_binary_outfile(infile: Path) -> Path:
    if infile.suffix.lower() == ".h5":
        return infile.with_suffix("")
    return infile


def _normalize_file_type(metadata: dict) -> dict:
    file_type = metadata.get("FILE_TYPE", "")
    if file_type in FILE_TYPE_NORMALIZE:
        metadata["FILE_TYPE"] = FILE_TYPE_NORMALIZE[file_type]
    elif file_type.startswith("."):
        metadata["FILE_TYPE"] = file_type.lstrip(".")
    return metadata


def _denormalize_file_type(metadata: dict) -> dict:
    file_type = metadata.get("FILE_TYPE", "")
    if file_type in FILE_TYPE_DENORMALIZE:
        metadata["FILE_TYPE"] = FILE_TYPE_DENORMALIZE[file_type]
    return metadata


def convert2h5(infile: str | Path, outfile: str | Path | None = None, file_type: str | None = None) -> Path:
    infile = _resolve_input(Path(infile))
    outfile = Path(outfile).expanduser().resolve() if outfile else _default_outfile(infile)

    data, metadata = readfile.read(str(infile))
    if file_type:
        metadata["FILE_TYPE"] = file_type
    else:
        metadata = _normalize_file_type(metadata)

    writefile.write(data, out_file=str(outfile), metadata=metadata)
    print(f"wrote {outfile}")
    return outfile


def convert_h5_to_binary(
    infile: str | Path,
    outfile: str | Path | None = None,
    file_type: str | None = None,
) -> Path:
    infile = _resolve_input(Path(infile))
    outfile = Path(outfile).expanduser().resolve() if outfile else _default_binary_outfile(infile)

    data, metadata = readfile.read(str(infile))
    if file_type:
        metadata["FILE_TYPE"] = file_type
    else:
        metadata = _denormalize_file_type(metadata)

    writefile.write(data, out_file=str(outfile), metadata=metadata)
    print(f"wrote {outfile}")
    print(f"wrote {outfile}.rsc")
    return outfile


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    try:
        if args.reverse:
            convert_h5_to_binary(args.infile, args.outfile, args.file_type)
        else:
            convert2h5(args.infile, args.outfile, args.file_type)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
