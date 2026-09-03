"""Ad-hoc CLI to filter the normalized deals and print them.

Every option takes a comma-separated list, same as the app's shareable URL, since it
is passed straight to FilterState.from_query -- the one place filter parsing lives.

Examples:
  python scripts/query.py --technologies "Antibody Drug Conjugate"
  python scripts/query.py --technologies-raw "Antibody Drug Conjugate,ADCs"
  python scripts/query.py --deal-types License --years 2023,2024,2025
  python scripts/query.py --years 2022,2023 --quarters 3,4
  python scripts/query.py --geographies China --phases "Phase 2,Phase 3"
  python scripts/query.py --technologies "CAR therapy" --money --limit 10
  python scripts/query.py --exclude-mega-deals --money --all
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from lib.data import load_deals
from lib.filters import FilterState, apply_filters

DEFAULT_COLUMNS = [
    "deal_date",
    "originator",
    "collaborators",
    "technologies",
    "indications",
    "phase",
    "deal_type_groups",
    "based_at",
]
MONEY_COLUMNS = ["upfront_musd", "total_musd"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--years", help='comma-separated, e.g. "2023,2024,2025"')
    parser.add_argument("--quarters", help='comma-separated (1-4), e.g. "3,4"')
    parser.add_argument("--indications", help="comma-separated mapped groups, e.g. Oncology,INI")
    parser.add_argument("--indications-raw", help="comma-separated raw values, e.g. Immunology")
    parser.add_argument("--technologies", help='comma-separated mapped groups, e.g. "CAR therapy"')
    parser.add_argument("--technologies-raw", help='comma-separated raw values, e.g. "CAR T cells"')
    parser.add_argument("--deal-types", help="comma-separated mapped groups, e.g. License,M&A")
    parser.add_argument("--deal-types-raw", help="comma-separated raw values, e.g. Co-development")
    parser.add_argument("--geographies", help="comma-separated, e.g. USA,China")
    parser.add_argument("--phases", help='comma-separated, e.g. "Phase 2,Phase 3"')
    parser.add_argument(
        "--exclude-mega-deals",
        action="store_true",
        help=(
            "drop deals >= the mega-deal threshold from this listing (row-level, off by "
            "default here -- distinct from the app's value-chart toggle, which is on by "
            "default and never affects which rows appear, only sums/medians)"
        ),
    )
    parser.add_argument("--money", action="store_true", help="also print upfront/total $M")
    parser.add_argument("--limit", type=int, default=50, help="max rows to print (default 50)")
    parser.add_argument(
        "--all", action="store_true", help="print every matching row, ignore --limit"
    )
    parser.add_argument("--count-only", action="store_true", help="print only the match count")
    args = parser.parse_args()

    query = {
        key: value
        for key, value in {
            "years": args.years,
            "quarters": args.quarters,
            "indications": args.indications,
            "indications_raw": args.indications_raw,
            "technologies": args.technologies,
            "technologies_raw": args.technologies_raw,
            "deal_types": args.deal_types,
            "deal_types_raw": args.deal_types_raw,
            "geographies": args.geographies,
            "phases": args.phases,
        }.items()
        if value
    }

    filters = FilterState.from_query(query)
    deals = apply_filters(load_deals(), filters)
    if args.exclude_mega_deals:
        deals = deals[~deals["is_mega_deal"]]

    mega_note = " (mega deals excluded)" if args.exclude_mega_deals else ""
    print(f"{len(deals)} deals match{mega_note} -- filters: {query or 'none'}\n")
    if args.count_only:
        return 0

    columns = DEFAULT_COLUMNS + (MONEY_COLUMNS if args.money else [])
    result = deals.sort_values("deal_date", ascending=False, na_position="last")[columns]
    if not args.all:
        result = result.head(args.limit)

    with pd.option_context(
        "display.max_rows", None, "display.max_colwidth", 40, "display.width", 200
    ):
        print(result.to_string(index=False))

    if not args.all and len(deals) > args.limit:
        remaining = len(deals) - args.limit
        print(f"\n... {remaining} more rows not shown. Use --all or --limit N to see them.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
