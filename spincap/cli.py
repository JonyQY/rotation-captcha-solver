"""Command-line interface for a local image; emits machine-readable JSON."""
import argparse
import json
import math
from pathlib import Path
import sys
from time import perf_counter

from . import __version__
from .api import AngleSession, DEFAULT_TIERS, offset_for, read_angle, read_all


def run_stdio():
    """One local worker, one JSON request/response per line; EOF stops it."""
    started = perf_counter()
    session = AngleSession()
    print(json.dumps({'type': 'ready', 'init_seconds': round(perf_counter() - started, 3)}),
          flush=True)
    for line in sys.stdin:
        started = perf_counter()
        request_id = None
        result = {'type': 'result', 'angle_cw': None, 'usable': False}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('request must be a JSON object')
            request_id = request.get('id')
            image_value = request.get('image')
            if not isinstance(image_value, str):
                raise ValueError('image must be an absolute local file path')
            image = Path(image_value)
            if not image.is_absolute() or not image.is_file():
                raise ValueError('image must be an existing absolute local file')
            pixels = request.get('pixels_per_turn')
            if pixels is not None and (isinstance(pixels, bool)
                    or not isinstance(pixels, (int, float))
                    or not math.isfinite(pixels) or pixels <= 0):
                raise ValueError('pixels_per_turn must be finite and positive')
            complement = request.get('complement', False)
            if not isinstance(complement, bool):
                raise ValueError('complement must be a boolean')
            angle = session.read_angle(image)
            result.update(angle_cw=angle, usable=angle is not None)
            if angle is not None and pixels is not None:
                result['offset_px'] = offset_for(angle, pixels, complement=complement)
        except Exception as error:
            result['error'] = str(error)
        result.update(id=request_id, elapsed_ms=round((perf_counter() - started) * 1000, 2))
        print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Estimate the clockwise roll of a local image.")
    parser.add_argument("image", type=Path, nargs='?')
    parser.add_argument("--stdio", action="store_true", help="Keep models loaded; read JSON lines from stdin")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--all", action="store_true", help="Return each reader's result without consensus")
    parser.add_argument("--tier", choices=DEFAULT_TIERS, help="Use a single tier without consensus")
    parser.add_argument("--pixels-per-turn", type=float)
    parser.add_argument("--complement", action="store_true")
    args = parser.parse_args(argv)
    if args.stdio:
        if args.image or args.all or args.tier or args.pixels_per_turn is not None or args.complement:
            parser.error('--stdio accepts options in each JSON request, not CLI image/options')
        try:
            return run_stdio()
        except Exception as error:
            print(str(error), file=sys.stderr)
            return 1
    if args.image is None:
        parser.error('image is required unless --stdio is used')
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
