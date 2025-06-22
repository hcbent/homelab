#!/usr/bin/env python3

import argparse
import os
import sys
import yaml
from urllib.parse import urlparse # For parsing the ES URL
from elasticsearch8 import Elasticsearch, exceptions

# --- Configuration Defaults ---
DEFAULT_ES_URL = "http://localhost:9200" # Default full URL
DEFAULT_CONFIG_FILE_PATH = "/etc/elastic/cluster.yaml"
DEFAULT_ILM_POLICY_NAME = "ela-default" # Default ILM policy for data streams

def load_yaml_config(file_path):
    """Loads configuration from a YAML file."""
    try:
        with open(file_path, 'r') as f:
            config = yaml.safe_load(f)
        return config if config else {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file '{file_path}': {e}")
        return {}
    except Exception as e:
        print(f"Error reading config file '{file_path}': {e}")
        return {}

def create_es_role(es_client, role_name, index_pattern_name):
    """
    Creates or updates a read-only role in Elasticsearch for a specific index pattern
    (which can be an index, alias, or data stream name).
    Kibana access (like Discover/Dashboards) should be managed by assigning
    users an additional, separate Kibana access role (e.g., 'kibana_user').
    """
    role_body = {
        "cluster": [],
        "indices": [
            {
                "names": [index_pattern_name], # This can be an index, alias, or data stream
                "privileges": ["read", "view_index_metadata"],
                "allow_restricted_indices": False
            }
        ]
        # 'kibana' block removed due to 'unexpected field [kibana]' error,
        # likely indicating an older ES version or a license level (e.g., Basic)
        # that doesn't support direct Kibana feature privileges in this role definition.
    }
    try:
        es_client.security.put_role(name=role_name, body=role_body)
        print(f"  Successfully created/updated role: '{role_name}' for pattern '{index_pattern_name}'.")
        print(f"  Note: This role grants data access. For Kibana Discover/Dashboard access, users need an additional Kibana access role.")
        return True
    except exceptions.ElasticsearchException as e:
        print(f"  Error creating/updating role '{role_name}': {e}")
        if hasattr(e, 'info') and e.info:
            print(f"    Error details: {e.info}")
        print(f"  Exception type: {type(e)}")
        return False

def create_index_template(es_client, template_name, data_stream_name, ilm_policy_name):
    """
    Creates or updates an index template for a data stream in Elasticsearch.
    The template defines that matching indices will form a data stream
    and assigns the specified ILM policy.
    """
    template_body = {
        "index_patterns": [data_stream_name],
        "data_stream": {},
        "template": {
            "settings": {
                "index.lifecycle.name": ilm_policy_name
            },
            "mappings": {
                "properties": {
                    "@timestamp": {
                        "type": "date"
                    }
                }
            }
        },
        "priority": 200,
    }
    try:
        es_client.indices.put_index_template(name=template_name, body=template_body)
        print(f"  Successfully created/updated index template: '{template_name}' for data stream '{data_stream_name}' (ILM: '{ilm_policy_name}')")
        return True
    except exceptions.ElasticsearchException as e:
        print(f"  Error creating/updating index template '{template_name}': {e}")
        if hasattr(e, 'info') and e.info:
            print(f"    Error details: {e.info}")
        elif hasattr(e, 'meta') and e.meta and hasattr(e.meta, 'body') and e.meta.body:
             print(f"    Error body: {e.meta.body}")
        print(f"  Exception type: {type(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Create Elasticsearch roles and data stream index templates.")
    parser.add_argument(
        "--prefixes",
        nargs='+',
        required=True,
        help="List of prefixes (e.g., dev staging prod)"
    )
    parser.add_argument(
        "--subsystems",
        nargs='+',
        required=True,
        help="List of subsystems (e.g., users orders audit)"
    )
    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE_PATH,
        help=f"Path to YAML configuration file for Elasticsearch connection (default: {DEFAULT_CONFIG_FILE_PATH})"
    )
    parser.add_argument(
        "--es-url",
        help=f"Full Elasticsearch URL (e.g., https://es.example.com:9200). Overrides config file. Default: {DEFAULT_ES_URL}"
    )
    parser.add_argument("--es-api-key", help="Elasticsearch API key (e.g., 'id:key_value') (overrides config file)")
    parser.add_argument("--es-user", help="Elasticsearch username for basic authentication (overrides config file)")
    parser.add_argument("--es-password", help="Elasticsearch password for basic authentication (overrides config file)")
    parser.add_argument("--ca-certs", help="Path to CA certificate file for HTTPS (overrides config file)")
    parser.add_argument(
        "--ilm-policy",
        default=DEFAULT_ILM_POLICY_NAME,
        help=f"Name of the ILM policy to assign to the data streams (default: {DEFAULT_ILM_POLICY_NAME}). This policy must exist in Elasticsearch."
    )

    args = parser.parse_args()

    # --- Initialize Connection Parameters ---
    conn_details = {
        "url": DEFAULT_ES_URL,
        "api_key": None,
        "username": None,
        "password": None,
        "ca_certs": None,
    }

    config_file_path_to_check = args.config_file
    config_file_is_default_and_not_found = (args.config_file == DEFAULT_CONFIG_FILE_PATH and not os.path.exists(DEFAULT_CONFIG_FILE_PATH))

    if os.path.exists(config_file_path_to_check):
        print(f"Loading configuration from '{config_file_path_to_check}'...")
        yaml_config = load_yaml_config(config_file_path_to_check)
        if yaml_config and "elasticsearch" in yaml_config:
            es_conf = yaml_config["elasticsearch"]
            conn_details["url"] = es_conf.get("url", conn_details["url"])
            conn_details["api_key"] = es_conf.get("api_key", conn_details["api_key"])
            conn_details["username"] = es_conf.get("username", conn_details["username"])
            conn_details["password"] = es_conf.get("password", conn_details["password"])
            conn_details["ca_certs"] = es_conf.get("ca_certs", conn_details["ca_certs"])
        elif yaml_config:
             print(f"Warning: 'elasticsearch' key not found in '{config_file_path_to_check}'. Using defaults and command-line overrides.")
    elif not config_file_is_default_and_not_found :
        if args.config_file != DEFAULT_CONFIG_FILE_PATH or os.path.exists(args.config_file):
            print(f"Warning: Specified config file '{config_file_path_to_check}' not found or failed to load. Using defaults and command-line overrides.")

    if args.es_url is not None: conn_details["url"] = args.es_url
    if args.es_api_key is not None: conn_details["api_key"] = args.es_api_key
    if args.es_user is not None: conn_details["username"] = args.es_user
    if args.es_password is not None: conn_details["password"] = args.es_password
    if args.ca_certs is not None: conn_details["ca_certs"] = args.ca_certs

    try:
        parsed_url = urlparse(conn_details["url"])
        if not parsed_url.scheme or not parsed_url.netloc:
            print(f"Error: Invalid Elasticsearch URL format: '{conn_details['url']}'. Must include scheme (http/https) and host.")
            sys.exit(1)
    except ValueError as e:
        print(f"Error: Could not parse Elasticsearch URL '{conn_details['url']}': {e}")
        sys.exit(1)

    # --- Elasticsearch Client Initialization ---
    es_client_params = {
        "hosts": [conn_details["url"]],
        "request_timeout": 10,
        "retry_on_timeout": True
    }

    if conn_details["api_key"]:
        es_client_params["api_key"] = conn_details["api_key"]
    elif conn_details["username"] and conn_details["password"]:
        es_client_params["basic_auth"] = (conn_details["username"], conn_details["password"])

    if parsed_url.scheme == "https":
        if conn_details["ca_certs"]:
            es_client_params["ca_certs"] = conn_details["ca_certs"]
            es_client_params["verify_certs"] = True
    else:
        if "ca_certs" in es_client_params: del es_client_params["ca_certs"]
        if "verify_certs" in es_client_params: del es_client_params["verify_certs"]

    debug_params = {k: v for k, v in es_client_params.items()}
    if "basic_auth" in debug_params and debug_params["basic_auth"]:
        debug_params["basic_auth"] = (debug_params["basic_auth"][0], "*******")
    if "api_key" in debug_params and debug_params["api_key"]:
        if isinstance(debug_params["api_key"], str) and ':' in debug_params["api_key"]:
            parts = debug_params["api_key"].split(':', 1)
            debug_params["api_key"] = f"{parts[0]}:*******"
        elif isinstance(debug_params["api_key"], tuple):
            debug_params["api_key"] = (debug_params["api_key"][0], "*******")

    print(f"\nAttempting to connect to Elasticsearch with parameters: {debug_params}")

    try:
        es = Elasticsearch(**es_client_params)
        print("Elasticsearch client initialized. Pinging cluster...")
        if not es.ping():
            print("\n--- CONNECTION FAILED (ping) ---")
            print("Elasticsearch ping() returned False.")
            print("This means the client could reach the host/port, but the cluster did not respond successfully to the ping.")
            # ... (rest of ping failure details)
            sys.exit(1)
        print("Successfully connected to Elasticsearch and ping was successful.")

    except exceptions.AuthenticationException as e:
        print("\n--- AUTHENTICATION ERROR ---")
        print(f"Message: {e}")
        sys.exit(1)
    # ... (other specific exception handling) ...
    except exceptions.TransportError as e:
        print("\n--- TRANSPORT ERROR ---")
        print(f"Message: {e}")
        if hasattr(e, 'info') and e.info: print(f"  Details: {e.info}")
        if hasattr(e, 'status_code'): print(f"  Status Code: {e.status_code}")
        sys.exit(1)
    except exceptions.ElasticsearchException as e:
        print("\n--- ELASTICSEARCH CLIENT ERROR ---")
        print(f"Message: {e}")
        sys.exit(1)
    except Exception as e:
        print("\n--- UNEXPECTED PYTHON ERROR DURING CONNECTION ---")
        print(f"Message: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # --- Resource Creation Logic ---
    roles_created_count = 0
    roles_failed_count = 0
    templates_created_count = 0
    templates_failed_count = 0

    print(f"\nStarting resource creation process (ILM Policy for templates: '{args.ilm_policy}')...")
    print(f"Note: The ILM policy '{args.ilm_policy}' must exist in Elasticsearch.")

    for prefix in args.prefixes:
        clean_prefix = prefix.lower().strip()
        for subsystem in args.subsystems:
            clean_subsystem = subsystem.lower().strip()

            data_stream_name = f"{clean_prefix}-{clean_subsystem}"
            role_name = f"{clean_prefix}_{clean_subsystem}_access"
            template_name = f"{clean_prefix}_{clean_subsystem}_ds_template"

            print(f"\nProcessing: prefix='{clean_prefix}', subsystem='{clean_subsystem}'")
            print(f"  Target data stream name: '{data_stream_name}'")
            print(f"  Role to create/update: '{role_name}' (for data stream '{data_stream_name}')")
            print(f"  Index template to create/update: '{template_name}' (for data stream '{data_stream_name}')")

            if create_es_role(es, role_name, data_stream_name):
                roles_created_count += 1
            else:
                roles_failed_count += 1

            if create_index_template(es, template_name, data_stream_name, ilm_policy_name=args.ilm_policy):
                templates_created_count += 1
            else:
                templates_failed_count += 1

    print("\n--- Summary ---")
    print(f"Roles successfully created/updated: {roles_created_count}")
    print(f"Roles failed to create/update: {roles_failed_count}")
    print(f"Index templates successfully created/updated: {templates_created_count}")
    print(f"Index templates failed to create/update: {templates_failed_count}")

    if roles_failed_count > 0 or templates_failed_count > 0:
        print("\nSome operations failed. Please review the logs above.")
        sys.exit(1)
    else:
        print("\nAll operations completed successfully.")

if __name__ == "__main__":
    main()
