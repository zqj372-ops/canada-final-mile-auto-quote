"""Query tariff references or logistics knowledge through the bot service API.

Reuse the private session created by personal_wecom.py login; no new credential
store and no source-site cookies or credentials are accepted on the command line.
"""
import argparse
import json
from pathlib import Path

from personal_wecom import ClientError, read_session, request


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--session", default=str(Path.home() / ".config/personal-wecom/session.json"))
    cli.add_argument("--query")
    cli.add_argument("--destination", choices=["CA", "US"])
    cli.add_argument("--origin", help="Country of origin; omitted origin defaults to China (CN)")
    cli.add_argument("--material")
    cli.add_argument("--use")
    cli.add_argument("--code-country", choices=["CN", "CA", "US"])
    cli.add_argument("--rule-date")
    cli.add_argument("--knowledge", help="Ask a logistics/customs knowledge question")
    cli.add_argument("--topic", help="Previous knowledge topic ID for a follow-up question")
    args = cli.parse_args()
    if args.knowledge is not None and any(getattr(args, name) is not None for name in
                                         ("query", "destination", "origin", "material", "use", "code_country", "rule_date")):
        cli.error("--knowledge cannot be combined with tariff-query fields")
    if args.topic and args.knowledge is None:
        cli.error("--topic requires --knowledge")
    try:
        session = read_session(Path(args.session).expanduser())
        if args.knowledge is not None:
            payload = {"question": args.knowledge}
            if args.topic:
                payload["previous_topic_id"] = args.topic
            endpoint = "/customs/knowledge-query"
        else:
            payload = {key: value for key, value in vars(args).items() if key not in {"session", "knowledge", "topic"} and value is not None}
            endpoint = "/customs/reference-query"
        result = request(session["base_url"], endpoint, method="POST", data=payload, credential=session["credential"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"needs_input", "manual_review", "answered", "requires_lookup", "needs_review"} else 1
    except (ClientError, OSError, ValueError, KeyError):
        print(json.dumps({"status": "unavailable", "message": "请求未完成，请检查登录会话、服务权限和连接。未自动重试。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
