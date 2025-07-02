#!/usr/bin/env python3

import argparse

from elasticsearch import Elasticsearch


def apply_lifecycle_policy(
    es_host,
    index_pattern,
    username,
    password,
    policy_name="deepfreeze-policy-norollover",
):
    es = Elasticsearch(es_host, basic_auth=(username, password))

    # Get all indices that match the pattern
    #indices = es.indices.get(index=index_pattern, expand_wildcards='all')
    indices = es.indices.get(index=index_pattern)

    print(f"🔍 Found {len(indices)} indices matching pattern '{index_pattern}'")

    for index in indices:
        # Get current settings to check for existing lifecycle policy
        current_settings = es.indices.get_settings(index=index)
        existing_policy = current_settings.get(index, {}).get("settings", {}).get("index.lifecycle.name")
        
        if existing_policy:
            print(f"⚠️ Skipping index '{index}' - already has lifecycle policy '{existing_policy}'")
        else:
            # Apply the lifecycle policy
            settings = {"index": {"lifecycle": {"name": policy_name}}}
            try:
                es.indices.put_settings(index=index, settings=settings)
            except:
                print(f"‼️ Couldn't apply lifecycle policy '{policy_name}' to index '{index}'")
            finally:
                print(f"✅ Applied lifecycle policy '{policy_name}' to index '{index}'")

#    for index in indices:
#        # Apply the lifecycle policy
#        print(f"🔄 Applying lifecycle policy '{policy_name}' to index '{index}'...")
#        settings = {"index": {"lifecycle": {"name": policy_name}}}
#        es.indices.put_settings(index=index, body=settings)
#        print(f"✅ Applied lifecycle policy '{policy_name}' to index '{index}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Apply a lifecycle policy to matching indices in Elasticsearch.",
        epilog="Example: python script.py http://localhost:9200 'logs-*' user pass --policy my-policy",
    )
    parser.add_argument(
        "--host",
        help="Elasticsearch host (e.g., http://localhost:9200)",
        default="http://localhost:9200",
    )
    parser.add_argument(
        "--index_pattern",
        help="Index pattern to match (e.g., logs-*)",
        default='.ds-metrics-homeassistant*',
    )
    parser.add_argument("--username", help="Elasticsearch username", default="bret")
    parser.add_argument(
        "--password",
        help="Elasticsearch password",
        default="2xqT2IO1OQ%tfMHP",
    )
    parser.add_argument(
        "--policy",
        default="deepfreeze-policy-norollover",
        help="Lifecycle policy name (default: deepfreeze-policy-norollover)",
    )

    args = parser.parse_args()

    print("🔄 Connecting to Elasticsearch...")
    apply_lifecycle_policy(
        es_host=args.host,
        index_pattern=args.index_pattern,
        username=args.username,
        password=args.password,
        policy_name=args.policy,
    )
    print("🎉 Done!")
