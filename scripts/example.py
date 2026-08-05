#!/usr/bin/env python3
"""Read-only Therefore connection and metadata smoke test."""

import argparse
import sys
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "references"
sys.path.insert(0, str(REFERENCE_DIR))

from therefore_client import ThereforeClient, build_config_from_env, load_env  # noqa: E402


def _count_tree_items(items):
    counts = {"folders": 0, "categories": 0, "case_definitions": 0}
    key_by_type = {1: "folders", 2: "categories", 3: "case_definitions"}
    for item in items:
        key = key_by_type.get(item.get("ItemType"))
        if key:
            counts[key] += 1
        child_counts = _count_tree_items(item.get("ChildItems") or [])
        for name, value in child_counts.items():
            counts[name] += value
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="path to THEREFORE_* settings")
    parser.add_argument("--category", type=int, help="optional CategoryNo to inspect")
    args = parser.parse_args()

    config = build_config_from_env(load_env(args.env_file))
    if not config.base_url:
        parser.error("THEREFORE_BASE_URL is required")

    client = ThereforeClient(config)
    token = client.get_connection_token()
    print(f"Connected: {'yes' if token.get('Token') else 'response received'}")

    tree = client.get_categories_tree()
    counts = _count_tree_items(tree.get("TreeItems") or [])
    print(
        "Accessible tree: "
        f"{counts['folders']} folders, "
        f"{counts['categories']} categories, "
        f"{counts['case_definitions']} case definitions"
    )

    if args.category is not None:
        category = client.get_category_info(args.category)
        print(
            f"Category {args.category}: {category.get('Name', '<unnamed>')} "
            f"({len(category.get('CategoryFields') or [])} fields)"
        )

if __name__ == "__main__":
    main()
