"""Prepare a bounded batch of queued diagnostic contexts. No model calls."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.services.diagnostic_context_worker import process_context_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    print(f"Prepared {process_context_batch(limit=args.limit)} diagnostic records.")


if __name__ == "__main__":
    main()
