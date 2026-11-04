"""python examples/read_image.py /path/to/puzzle.png"""
import sys
from spincap import read_angle, offset_for

angle = read_angle(sys.argv[1])
if angle is None:
    print("No reliable consensus. Do not submit this result.")
    raise SystemExit(2)
print({"angle_cw": angle,
       "offset_px": offset_for(angle, pixels_per_turn=240, complement=True)})
