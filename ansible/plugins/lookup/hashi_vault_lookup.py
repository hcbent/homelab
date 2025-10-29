#!/usr/bin/env python3
"""
Ansible lookup plugin for HashiCorp Vault
Retrieves secrets from Vault KV v2 secrets engine

Usage in playbooks:
  vars:
    freenas_api_key: "{{ lookup('hashi_vault_lookup', 'secret/homelab/freenas/credentials:api_key') }}"

Environment variables:
  VAULT_ADDR: Vault server address (default: https://vault.lab.thewortmans.org:8200)
  VAULT_TOKEN: Vault authentication token
  VAULT_SKIP_VERIFY: Skip TLS verification (default: false)
"""

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
import os
import json

try:
    import hvac
    HAS_HVAC = True
except ImportError:
    HAS_HVAC = False

class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if not HAS_HVAC:
            raise AnsibleError("hvac library is required. Install with: pip install hvac")

        if not terms:
            raise AnsibleError("hashi_vault_lookup requires a path")

        # Get Vault configuration from environment
        vault_addr = os.getenv('VAULT_ADDR', 'https://vault.lab.thewortmans.org:8200')
        vault_token = os.getenv('VAULT_TOKEN')
        vault_skip_verify = os.getenv('VAULT_SKIP_VERIFY', 'false').lower() == 'true'

        if not vault_token:
            raise AnsibleError("VAULT_TOKEN environment variable must be set")

        # Initialize Vault client
        client = hvac.Client(
            url=vault_addr,
            token=vault_token,
            verify=not vault_skip_verify
        )

        if not client.is_authenticated():
            raise AnsibleError("Failed to authenticate with Vault")

        ret = []
        for term in terms:
            # Parse the term (format: path:key)
            if ':' in term:
                path, key = term.rsplit(':', 1)
            else:
                path = term
                key = None

            # Read secret from Vault
            try:
                # For KV v2, we need to use the /data/ path
                if not path.startswith('secret/data/'):
                    path = path.replace('secret/', 'secret/data/', 1)

                secret = client.secrets.kv.v2.read_secret_version(
                    path=path.replace('secret/data/', '')
                )

                data = secret['data']['data']

                if key:
                    ret.append(data.get(key, ''))
                else:
                    ret.append(data)

            except Exception as e:
                raise AnsibleError(f"Failed to read secret from Vault: {str(e)}")

        return ret
