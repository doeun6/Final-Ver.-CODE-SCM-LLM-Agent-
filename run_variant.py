"""Diagnostic safety/initial-stock intervention; scm/ stays unchanged.

Safety stock applies throughout the shared warm-up AND evaluation of this
setting. The original defaults (safety stock 0, initial inventory 0) are retained.
"""
import argparse
import sys

from variant_support import add_common_arguments, run_intervention


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser, default_budget=8)
    args = parser.parse_args(argv)
    return run_intervention(args, __file__, "safety_stock_and_initial_inventory")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
