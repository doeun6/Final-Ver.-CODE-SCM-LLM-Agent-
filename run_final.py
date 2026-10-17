"""Run the combined V1/V2/ownership/Q_base version with explicit safety stock.

--safety-stock is required: the caller selects the environmental intervention;
the script never silently chooses whether to add stock during warm-up.
"""
import argparse
import sys

from run_qmean import QMEAN
from variant_support import add_common_arguments, run_intervention


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser, default_budget=10, require_safety_stock=True)
    return run_intervention(parser.parse_args(argv), __file__, "final_v1_v2_ownership_qmean", QMEAN)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
