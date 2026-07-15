#!/usr/bin/env python3
"""
Rate-proportional stratified image-set splitter.

Splits images named TITLE_NUMBER.EXT into N disjoint sets whose sizes are
proportional to display rates (1 : 3 : 5.88). Within each set, TITLE
composition mirrors the overall pool (per-title proportional split).

The reserved image `mean_selected_stimuli.png` is never split; optionally it
is copied into every set folder (shared stimulus with special rules).

Usage:
    # Inspect the plan (no files touched):
    python split_sets.py --src ./Pictures --seed 42 --dry-run

    # Create the sets for real (copies by default):
    python split_sets.py --src ./Pictures --out ./sets --seed 42

    # Tune the rate-1 base count (others scale by rate):
    python split_sets.py --src ./Pictures --base-count 40 --dry-run

    # Move or symlink instead of copy:
    python split_sets.py --src ./Pictures --out ./sets --action move
"""

import os
import re
import sys
import shutil
import random
import logging
import argparse
from collections import defaultdict

# ---------- Configuration ----------
DEFAULT_N_SETS = 3
SET_LABELS = ["rate_1", "rate_3", "rate_5_88"]

# Relative weights per set (the display rates).
RATE_WEIGHTS = [1.0, 3.0, 5.88]

# Base image count for the rate-1 set. Others scale from this.
DEFAULT_BASE_COUNT = 40

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

# Filenames excluded from splitting (case-insensitive). Shared across all sets.
EXCLUDED_FILENAMES = {"mean_selected_stimuli.png"}

# Parse TITLE from TITLE_NUMBER (title may itself contain underscores).
NAME_RE = re.compile(r"^(?P<title>.+)_(?P<number>\d+)$")


# ---------- Collection ----------
def collect_images(src, extensions):
    """Return sorted list of image paths in `src` (non-recursive),
    excluding EXCLUDED_FILENAMES (case-insensitive)."""
    if not os.path.isdir(src):
        raise FileNotFoundError(f"Source folder not found: {src}")

    exts = tuple(e.lower() for e in extensions)
    excluded_lower = {name.lower() for name in EXCLUDED_FILENAMES}

    files, excluded_found = [], []
    for f in os.listdir(src):
        full = os.path.join(src, f)
        if not os.path.isfile(full):
            continue
        if os.path.splitext(f)[1].lower() not in exts:
            continue
        if f.lower() in excluded_lower:
            excluded_found.append(f)
            continue
        files.append(full)

    for name in excluded_found:
        logging.info("Excluding reserved image (not split): %s", name)

    if not files:
        raise RuntimeError(f"No matching images found in {src}")

    return sorted(files)


# ---------- Target sizing ----------
def compute_targets(base_count, weights):
    """Return integer target sizes per set: round(base * weight)."""
    return [round(base_count * w) for w in weights]


# ---------- Splitting ----------
def split_group_weighted(items, weights, rng):
    """Split `items` across sets proportionally to `weights` using
    largest-remainder (Hamilton) apportionment. Sums exactly to len(items)."""
    items = list(items)
    rng.shuffle(items)
    n = len(items)
    total_w = sum(weights)

    ideal = [n * w / total_w for w in weights]
    floors = [int(x) for x in ideal]
    remainder = n - sum(floors)

    frac_order = sorted(
        range(len(weights)),
        key=lambda i: ideal[i] - floors[i],
        reverse=True,
    )
    counts = floors[:]
    for i in range(remainder):
        counts[frac_order[i % len(weights)]] += 1

    pieces, start = [], 0
    for c in counts:
        pieces.append(items[start:start + c])
        start += c
    return pieces


def reconcile_to_targets(assignments, targets, rng):
    """Trim over-full sets and pad under-full sets to match `targets`.
    Disjointness preserved via a shared leftover pool."""
    leftovers = []

    for s, target in enumerate(targets):
        overflow = len(assignments[s]) - target
        if overflow > 0:
            rng.shuffle(assignments[s])
            leftovers.extend(assignments[s][target:])
            assignments[s] = assignments[s][:target]

    rng.shuffle(leftovers)
    for s, target in enumerate(targets):
        shortfall = target - len(assignments[s])
        while shortfall > 0 and leftovers:
            assignments[s].append(leftovers.pop())
            shortfall -= 1
        if shortfall > 0:
            label = SET_LABELS[s] if s < len(SET_LABELS) else f"set_{s+1}"
            logging.warning("Set '%s' short by %d images (not enough total).",
                            label, shortfall)

    return assignments, leftovers


def verify_disjoint(assignments):
    """Raise if any image is assigned to more than one set."""
    seen = {}
    for s, paths in assignments.items():
        for p in paths:
            if p in seen:
                raise RuntimeError(
                    f"Image assigned to multiple sets: {p} "
                    f"(sets {seen[p]} and {s})"
                )
            seen[p] = s


# ---------- Plan ----------
def build_plan(files, n_sets, weights, base_count, seed):
    rng = random.Random(seed)
    logging.info("Using seed: %s", seed)

    targets = compute_targets(base_count, weights)
    total_target = sum(targets)
    logging.info("Target set sizes %s (total %d) for weights %s",
                 targets, total_target, weights)

    if total_target > len(files):
        raise ValueError(
            f"Need {total_target} images but only {len(files)} available. "
            f"Lower --base-count (currently {base_count})."
        )

    groups = defaultdict(list)
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        m = NAME_RE.match(stem)
        title = m.group("title") if m else stem
        if not m:
            logging.warning("Filename does not match TITLE_NUMBER: %s", stem)
        groups[title].append(path)

    assignments = {s: [] for s in range(n_sets)}
    for title in sorted(groups):
        pieces = split_group_weighted(groups[title], weights, rng)
        for s, piece in enumerate(pieces):
            assignments[s].extend(piece)

    assignments, leftovers = reconcile_to_targets(assignments, targets, rng)

    if leftovers:
        rng.shuffle(leftovers)
        logging.info("Distributing %d surplus image(s) evenly across sets.",
                     len(leftovers))
        # Round-robin, starting each pass from the smallest set to keep
        # distribution as even as possible.
        for i, path in enumerate(leftovers):
            # Assign to the currently smallest set (ties broken by index).
            s = i % n_sets
            assignments[s].append(path)
            logging.debug("Surplus %s -> set %d", os.path.basename(path), s)

    verify_disjoint(assignments)

    # Recompute effective sizes after surplus distribution.
    final_sizes = [len(assignments[s]) for s in range(n_sets)]
    logging.info("Final set sizes after surplus distribution: %s", final_sizes)

    return assignments, targets, leftovers


# ---------- Apply ----------
def apply_plan(assignments, out_root, action, dry_run):
    for s, paths in assignments.items():
        label = SET_LABELS[s] if s < len(SET_LABELS) else f"set_{s+1}"
        dest_dir = os.path.join(out_root, label)
        for src_path in paths:
            dest_path = os.path.join(dest_dir, os.path.basename(src_path))
            if dry_run:
                logging.debug("[dry] %s -> %s", src_path, dest_path)
                continue
            os.makedirs(dest_dir, exist_ok=True)
            if action == "symlink":
                os.symlink(os.path.abspath(src_path), dest_path)
            elif action == "move":
                shutil.move(src_path, dest_path)
            else:  # copy
                shutil.copy2(src_path, dest_path)


def distribute_shared_images(src, out_root, n_sets, extensions, action, dry_run):
    """Place each reserved/shared image into EVERY set folder (always copy)."""
    excluded_lower = {name.lower() for name in EXCLUDED_FILENAMES}
    exts = tuple(e.lower() for e in extensions)

    shared = [f for f in os.listdir(src)
              if f.lower() in excluded_lower
              and os.path.splitext(f)[1].lower() in exts
              and os.path.isfile(os.path.join(src, f))]

    if not shared:
        logging.warning("No reserved/shared image found in source: %s",
                        EXCLUDED_FILENAMES)
        return

    for f in shared:
        src_path = os.path.join(src, f)
        for s in range(n_sets):
            label = SET_LABELS[s] if s < len(SET_LABELS) else f"set_{s+1}"
            dest_dir = os.path.join(out_root, label)
            dest_path = os.path.join(dest_dir, f)
            if dry_run:
                logging.info("[dry] shared %s -> %s", f, dest_path)
                continue
            os.makedirs(dest_dir, exist_ok=True)
            if action == "symlink":
                os.symlink(os.path.abspath(src_path), dest_path)
            else:
                shutil.copy2(src_path, dest_path)

        if action == "move":
            logging.warning(
                "Shared image '%s' was COPIED (not moved) into all sets; "
                "original remains in source.", f)


# ---------- Main ----------
def main():
    parser = argparse.ArgumentParser(
        description="Split images into rate-proportional disjoint sets."
    )
    parser.add_argument("--src", required=True, help="Source image folder.")
    parser.add_argument("--out", default="./sets",
                        help="Output root folder (default ./sets).")
    parser.add_argument("--base-count", type=int, default=DEFAULT_BASE_COUNT,
                        help="Image count for rate-1 set; others scale by rate "
                             f"(default {DEFAULT_BASE_COUNT}).")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility.")
    parser.add_argument("--action", choices=("copy", "move", "symlink"),
                        default="copy", help="File operation (default copy).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report the plan without touching files.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose per-file logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        files = collect_images(args.src, IMAGE_EXTENSIONS)
        logging.info("Collected %d splittable images.", len(files))

        assignments, targets, _ = build_plan(
            files, DEFAULT_N_SETS, RATE_WEIGHTS, args.base_count, args.seed
        )

        logging.info("===== SET SIZE PLAN =====")
        for s, target in enumerate(targets):
            label = SET_LABELS[s] if s < len(SET_LABELS) else f"set_{s+1}"
            logging.info("  %-10s weight=%-5s target=%-4d actual=%d",
                         label, RATE_WEIGHTS[s], target, len(assignments[s]))
        logging.info("  TOTAL assigned=%d / available=%d",
                     sum(len(v) for v in assignments.values()), len(files))

        apply_plan(assignments, args.out, args.action, args.dry_run)
        distribute_shared_images(args.src, args.out, DEFAULT_N_SETS,
                                 IMAGE_EXTENSIONS, args.action, args.dry_run)

        if args.dry_run:
            logging.info("DRY RUN complete — no files were modified.")
        else:
            logging.info("Done. Sets written under: %s",
                         os.path.abspath(args.out))

    except (FileNotFoundError, RuntimeError, ValueError) as e:
        logging.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()