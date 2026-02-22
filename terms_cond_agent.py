from __future__ import annotations

import argparse
import time
from dataclasses import replace

from app.services.terms_cond_agent import load_terms_cond_agent_config, run_terms_cond_agent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check terms_cond table and send email when terms_cond=true."
    )
    parser.add_argument("--poll", action="store_true", help="Run continuously instead of a single pass.")
    parser.add_argument("--interval", type=float, default=None, help="Polling interval in seconds.")
    parser.add_argument("--max-rows", type=int, default=None, help="Maximum rows to process per run.")
    parser.add_argument("--dry-run", action="store_true", help="Do not send emails or update DB.")
    return parser


def _print_result(prefix: str, result: object) -> None:
    print(f"{prefix}: {result}")


def main() -> None:
    args = _build_parser().parse_args()
    config = load_terms_cond_agent_config()

    if args.interval is not None:
        config = replace(config, poll_interval_seconds=args.interval)
    if args.max_rows is not None:
        config = replace(config, max_rows_per_run=args.max_rows)

    if not args.poll:
        result = run_terms_cond_agent(config, dry_run=args.dry_run)
        _print_result("terms_cond_agent", result)
        return

    while True:
        result = run_terms_cond_agent(config, dry_run=args.dry_run)
        _print_result("terms_cond_agent", result)
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    main()
