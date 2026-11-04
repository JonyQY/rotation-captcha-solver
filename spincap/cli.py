"""Command-line interface for a local image; emits machine-readable JSON."""
import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .api import DEFAULT_TIERS, offset_for, read_angle, read_all


def main(argv=None):
    parser = argparse.ArgumentParser(description="Estimate the clockwise roll of a local image.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--all", action="store_true", help="Return each reader's result without consensus")
    parser.add_argument("--tier", choices=DEFAULT_TIERS, help="Use a single tier without consensus")
    parser.add_argument("--pixels-per-turn", type=float)
    parser.add_argument("--complement", action="store_true")
    args = parser.parse_args(argv)
    if not args.image.is_file():
        parser.error("image must be an existing local file")
    if args.pixels_per_turn is not None and args.pixels_per_turn <= 0:
        parser.error("--pixels-per-turn must be positive")
    try:
        tiers = (args.tier,) if args.tier else DEFAULT_TIERS
        if args.all:
            readings = read_all(args.image, tiers=tiers)
            print(json.dumps({"readings": readings}, ensure_ascii=True))
            return 0 if any(isinstance(v, (int, float)) for v in readings.values()) else 2
        angle = read_angle(args.image, tiers=tiers, baseline=args.tier or "max",
                           require_agreement=not bool(args.tier))
        result = {"angle_cw": angle, "usable": angle is not None}
        if angle is not None and args.pixels_per_turn is not None:
            result["offset_px"] = offset_for(angle, args.pixels_per_turn,
                                             complement=args.complement)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if angle is not None else 2
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
