"""Evaluate extraction with fixed labels. Local strategy makes no network calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.ai_assistant.evaluation import load_cases, run_case, summarize
from packages.ai_assistant.http_pool import close_model_http_clients


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strategies", default="local")
    parser.add_argument("--split", choices=["validation", "test"], default="test")
    parser.add_argument("--ai-config-id", type=int)
    parser.add_argument("--allow-model-requests", action="store_true")
    parser.add_argument("--budget-seconds", type=float, default=30)
    args = parser.parse_args()
    strategies = list(dict.fromkeys(args.strategies.split(",")))
    if not set(strategies).issubset({"local", "single", "dual"}) or not 1 <= args.budget_seconds <= 60:
        parser.error("Unknown strategy or budget outside 1–60 seconds")
    if set(strategies) - {"local"} and (not args.allow_model_requests or not args.ai_config_id):
        parser.error("Model evaluation requires --allow-model-requests and --ai-config-id")
    cases = [case for case in load_cases(args.dataset) if case.split == args.split]
    if not cases:
        parser.error("Selected split has no cases")
    client = None
    if set(strategies) - {"local"}:
        from apps.api.db.session import get_session_factory
        from apps.api.db.repositories.ai_model_config_repository import AIModelConfigRepository
        from apps.api.services.ai_quote_service import _select_ai_config
        from packages.ai_assistant.model_client import OpenAICompatibleClient, config_from_record
        with get_session_factory()() as db:
            repository = AIModelConfigRepository(db)
            config = _select_ai_config(repository, args.ai_config_id)
            client = OpenAICompatibleClient(config_from_record(config, api_key=repository.decrypt_api_key(config)))
    report = {"dataset": args.dataset.name, "split": args.split, "strategies": {}}
    try:
        for strategy in strategies:
            rows = [run_case(case, strategy, client=client, budget_seconds=args.budget_seconds) for case in cases]
            report["strategies"][strategy] = {"summary": summarize(rows), "cases": rows}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({name: result["summary"] for name, result in report["strategies"].items()}, ensure_ascii=False, indent=2))
    finally:
        close_model_http_clients()


if __name__ == "__main__":
    main()
