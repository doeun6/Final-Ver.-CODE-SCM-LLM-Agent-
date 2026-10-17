"""Append the supplied Q_base meaning sentence only while running CMT orders.

A and the D reference prompts stay unchanged. --safety-stock 10 combines both
interventions, including the changed safety stock during the warm-up.
"""
import argparse
import sys

from variant_support import add_common_arguments, run_intervention


# Keep the collaborator's treatment wording verbatim. A revised sentence is a
# different intervention and must use a new output folder.
QMEAN = (" Q_base = 0 means your on-hand inventory plus outstanding orders already cover the"
         " forecast demand for the next two periods and your current backlog; it is not a signal to build inventory.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser, default_budget=10)
    args = parser.parse_args(argv)
    return run_intervention(args, __file__, "q_base_meaning_sentence", QMEAN)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
