"""CLI for local list builds and dossier writes."""

from __future__ import annotations

import argparse
import json

from mobydick.audiences import normalize_audience
from mobydick.dossier import build_dossier
from mobydick.pipeline import build_enriched_list
from mobydick.store import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="mobydick", description="Moby Dick local runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build", help="Build an enriched list")
    build.add_argument("--audience", default="series_ab")
    build.add_argument("--count", type=int, default=100)
    build.add_argument("--funded-since", default="2024-01-01")
    build.add_argument("--no-enrich", action="store_true")

    dossier = sub.add_parser("dossier", help="Write a whale dossier")
    dossier.add_argument("--name", required=True)
    dossier.add_argument("--firm", required=True)
    dossier.add_argument("--title", default="")
    dossier.add_argument("--linkedin", default="")

    exclude = sub.add_parser("exclude-count", help="Show exclude list size")
    exclude.add_argument("--list", dest="list_name", default="series_ab")

    args = parser.parse_args()
    store = Store()
    if args.cmd == "build":
        result = build_enriched_list(
            normalize_audience(args.audience),
            args.count,
            funded_since=args.funded_since,
            enrich=not args.no_enrich,
            store=store,
        )
        print(json.dumps(result, indent=2))
        return
    if args.cmd == "dossier":
        result = build_dossier(
            args.name,
            args.firm,
            title=args.title,
            linkedin_url=args.linkedin,
            store=store,
        )
        print(result.get("markdown") or "")
        return
    print(json.dumps(store.exclude_count(args.list_name), indent=2))


if __name__ == "__main__":
    main()
