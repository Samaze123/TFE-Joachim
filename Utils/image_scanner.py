#!/usr/bin/env python3
"""Summarize PNG and JPEG files in a folder, grouped by dimensions."""

import argparse
import struct
import sys
from collections import defaultdict
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# SOF markers that carry dimensions (exclude DHT=C4, JPG=C8, DAC=CC)
SOF_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
}


def read_png_size(f) -> tuple[int, int]:
    """Read (width, height) from an already-opened PNG file object."""
    f.seek(0)
    header = f.read(24)  # 8 sig + 4 len + 4 "IHDR" + 4 width + 4 height
    if len(header) < 24 or header[:8] != PNG_SIGNATURE:
        raise ValueError("Not a valid PNG file")
    if header[12:16] != b"IHDR":
        raise ValueError("Missing IHDR chunk")
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def read_jpeg_size(f) -> tuple[int, int]:
    """Read (width, height) from an already-opened JPEG file object.

    Scans JPEG markers until an SOF segment (which holds dimensions).
    """
    f.seek(0)
    if f.read(2) != JPEG_SIGNATURE:
        raise ValueError("Not a valid JPEG file")

    while True:
        byte = f.read(1)
        if not byte:
            raise ValueError("Reached EOF without finding SOF marker")

        # Markers start with 0xFF; skip fill/padding bytes.
        if byte != b"\xff":
            continue

        # Consume any run of 0xFF fill bytes, land on the marker code.
        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker:
            raise ValueError("Truncated JPEG marker")

        code = marker[0]

        # Standalone markers with no length (RSTn, SOI, EOI, TEM) -> skip.
        if code in (0x01, 0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
            continue

        length_bytes = f.read(2)
        if len(length_bytes) < 2:
            raise ValueError("Truncated JPEG segment length")
        seg_length = struct.unpack(">H", length_bytes)[0]
        if seg_length < 2:
            raise ValueError("Invalid JPEG segment length")

        if code in SOF_MARKERS:
            # SOF payload: precision(1) height(2) width(2) ...
            data = f.read(5)
            if len(data) < 5:
                raise ValueError("Truncated SOF segment")
            height, width = struct.unpack(">HH", data[1:5])
            return width, height

        # Not an SOF; skip this segment's payload (length includes the 2 length bytes).
        f.seek(seg_length - 2, 1)


def read_image_size(path: Path) -> tuple[int, int]:
    """Detect format by signature and return (width, height)."""
    with path.open("rb") as f:
        sig = f.read(8)
        if sig[:8] == PNG_SIGNATURE:
            return read_png_size(f)
        if sig[:2] == JPEG_SIGNATURE:
            return read_jpeg_size(f)
        raise ValueError("Unsupported or unrecognized image format")


def collect_images(folder: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in folder.glob(pattern)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def summarize(folder: Path, recursive: bool = False) -> None:
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    files = collect_images(folder, recursive)
    if not files:
        print("No .png/.jpg/.jpeg files found.")
        return

    groups: dict[tuple[int, int], list[Path]] = defaultdict(list)
    errors: list[tuple[Path, str]] = []

    for path in files:
        try:
            groups[read_image_size(path)].append(path)
        except (ValueError, OSError, struct.error) as exc:
            errors.append((path, str(exc)))

    sorted_groups = sorted(groups.items(), key=lambda kv: (kv[0][0] * kv[0][1], kv[0]))
    total_valid = sum(len(v) for v in groups.values())

    print(f"\nScanned {len(files)} image file(s) in '{folder}'"
          f"{' (recursive)' if recursive else ''}\n")
    print(f"Found {len(sorted_groups)} distinct size(s), {total_valid} valid image(s).\n")

    for (w, h), members in sorted_groups:
        print(f"{w} x {h} px  (area {w * h:,})  -  {len(members)} file(s):")
        for path in sorted(members):
            display = path.relative_to(folder) if recursive else path.name
            print(f"    {display}")
        print()

    if errors:
        print(f"Skipped {len(errors)} unreadable/invalid file(s):")
        for path, msg in errors:
            print(f"    {path.name}: {msg}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize PNG/JPEG files grouped by dimensions."
    )
    parser.add_argument("folder", type=Path, help="Folder containing image files")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Include subfolders")
    args = parser.parse_args()

    summarize(args.folder, args.recursive)


if __name__ == "__main__":
    main()