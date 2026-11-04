"""No model or browser required. Demonstrates the consensus/callback API."""
from spincap import CallableReader, build_solver


def main():
    # These are simulated reader outputs, not image recognition or live results.
    readers = [CallableReader("reference", lambda _: 90.0),
               CallableReader("reader-b", lambda _: 91.0),
               CallableReader("reader-c", lambda _: 89.0)]
    solver = build_solver(readers, baseline="reference", pixels_per_turn=240)
    offsets = []

    def drag(offset):
        offsets.append(offset)
        return True

    report = solver.solve(
        1, fetch_image=lambda: "simulated-image", refresh=lambda: False,
        drag=drag, verify=lambda: (True, "simulated-success"))
    assert offsets == [60.0]
    print({"mode": "simulation", "offsets_px": offsets, "report": report.summary()})


if __name__ == "__main__":
    main()
