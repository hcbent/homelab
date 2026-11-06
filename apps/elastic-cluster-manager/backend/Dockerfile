# Stages: base (the app), tools (verified Terraform and provider), worker (base + tools), app (base alone).
# `app` is last, so a plain `docker build` gives the lean image used by the API and the migration job.
# The worker is built with `--target worker` (compose does this). Needs BuildKit, which sets TARGETARCH.

FROM python:3.12-slim AS base
RUN useradd --create-home --uid 10001 ecm
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir .


# ---- Terraform and the provider, each checked against a pinned SHA-256 -------------------------------------
# The checksums were taken from HashiCorp's signed SHA256SUMS (signature verified) for Terraform, and from the
# Terraform Registry and the provider's GitHub release (the two agree) for the provider. To upgrade, change a
# version and BOTH its checksums together; the build fails if the downloaded file does not match.
# PROVIDER_VERSION must equal PROVIDER_VERSION in app/provisioning/hcl.py (tests/test_worker_image.py checks).
FROM python:3.12-slim AS tools
ARG TARGETARCH
ARG TERRAFORM_VERSION=1.17.0
ARG TERRAFORM_SHA256_AMD64=c168cab7c637a8769fdb90089ddd19de701bc6ff8aca64dc2e2185fe46f59f67
ARG TERRAFORM_SHA256_ARM64=f32478134ffc6d710eec474bbd316652cdddc0f4e336973a3745e8d3a3309cdf
ARG PROVIDER_VERSION=0.119.0
ARG PROVIDER_SHA256_AMD64=c833d9f23dc118cf91b5f4fa84c2bcf2237db04bdd17fc1a075e7565440b8f7c
ARG PROVIDER_SHA256_ARM64=b46a1ee68d69be8544f159454c2630295df4cdd53450f85a6005127a45a5b2b4
COPY docker/fetch_tool.py /opt/fetch_tool.py
RUN set -eu; \
    case "${TARGETARCH:-}" in \
      amd64) tf_sha="$TERRAFORM_SHA256_AMD64"; provider_sha="$PROVIDER_SHA256_AMD64" ;; \
      arm64) tf_sha="$TERRAFORM_SHA256_ARM64"; provider_sha="$PROVIDER_SHA256_ARM64" ;; \
      *) echo "unsupported or unset TARGETARCH '${TARGETARCH:-}' (build with BuildKit on amd64 or arm64)" >&2; exit 1 ;; \
    esac; \
    python /opt/fetch_tool.py fetch \
      "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" \
      "$tf_sha" /tmp/terraform.zip; \
    python /opt/fetch_tool.py unzip-member /tmp/terraform.zip terraform /out/bin/terraform 755; \
    python /opt/fetch_tool.py fetch \
      "https://github.com/bpg/terraform-provider-proxmox/releases/download/v${PROVIDER_VERSION}/terraform-provider-proxmox_${PROVIDER_VERSION}_linux_${TARGETARCH}.zip" \
      "$provider_sha" \
      "/out/providers/registry.terraform.io/bpg/proxmox/terraform-provider-proxmox_${PROVIDER_VERSION}_linux_${TARGETARCH}.zip"


# ---- Ansible: a virtualenv of its own, every Python package from a hash-locked file, collections by SHA-256 --
# The venv keeps Ansible's dependencies (cryptography, jinja2, ...) from touching the app's. Every package comes
# from docker/ansible-requirements.txt, which lists every file hash of every dependency (regenerate it as the
# header of docker/ansible-requirements.in says), and pip refuses anything without a matching hash. The two
# collections are downloaded from Galaxy and kept only if they match the SHA-256 below, which equals the one
# Galaxy publishes for that version (checked 2026-11-06). Keep these versions equal to infra/ansible/requirements.yml
# (tests/test_worker_image.py checks). To upgrade, change a version and its checksum together.
FROM python:3.12-slim AS ansible
ARG ANSIBLE_POSIX_VERSION=2.2.2
ARG ANSIBLE_POSIX_SHA256=00a58c5d804c9adc99c3c3dc1b9f2246f4bb5f7337941440e0956f0e31c3b82b
ARG COMMUNITY_GENERAL_VERSION=13.5.0
ARG COMMUNITY_GENERAL_SHA256=54598287e0ea0504aee2d32c884208ddf26f3ac41e0b4e773ff514af210787c4
COPY docker/fetch_tool.py /opt/fetch_tool.py
COPY docker/ansible-requirements.txt /tmp/ansible-requirements.txt
RUN set -eu; \
    python -m venv /opt/ansible; \
    /opt/ansible/bin/pip install --no-cache-dir --require-hashes --no-deps -r /tmp/ansible-requirements.txt; \
    galaxy="https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/artifacts"; \
    python /opt/fetch_tool.py fetch "$galaxy/ansible-posix-${ANSIBLE_POSIX_VERSION}.tar.gz" \
      "$ANSIBLE_POSIX_SHA256" /tmp/collections/ansible-posix.tar.gz; \
    python /opt/fetch_tool.py fetch "$galaxy/community-general-${COMMUNITY_GENERAL_VERSION}.tar.gz" \
      "$COMMUNITY_GENERAL_SHA256" /tmp/collections/community-general.tar.gz; \
    /opt/ansible/bin/ansible-galaxy collection install --no-deps -p /opt/ansible/collections \
      /tmp/collections/ansible-posix.tar.gz /tmp/collections/community-general.tar.gz


# ---- The worker: the app plus Terraform, the vendored provider, Ansible and an SSH client -------------------
# The playbooks and roles come from a named build context, ecm_ansible (infra/ansible), which compose supplies.
# A plain `docker build --target worker` must pass --build-context ecm_ansible=../infra/ansible.
FROM base AS worker
USER root
COPY --from=tools /out/bin/terraform /usr/local/bin/terraform
# Terraform installs the provider from here with -plugin-dir and never downloads anything at run time.
COPY --from=tools /out/providers /opt/ecm/terraform-providers
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ansible /opt/ansible /opt/ansible
COPY --from=ecm_ansible . /opt/ecm/ansible
# Only the entry points go on PATH. Putting /opt/ansible/bin first would shadow the app's own python.
RUN for tool in ansible ansible-playbook ansible-galaxy ansible-runner; do \
        ln -s "/opt/ansible/bin/$tool" "/usr/local/bin/$tool"; \
    done \
    && terraform version \
    && mkdir -p /data/clusters && chown ecm /data/clusters
ENV ECM_TERRAFORM_PLUGIN_DIR=/opt/ecm/terraform-providers \
    ECM_TF_WORKSPACE_ROOT=/data/clusters \
    ECM_ANSIBLE_DIR=/opt/ecm/ansible \
    ANSIBLE_COLLECTIONS_PATH=/opt/ansible/collections
USER ecm
# Fail the build, not the first job, if the app user cannot read what Terraform needs or write its workspaces,
# or if Ansible, its collections, the SSH client or the playbooks are not usable as that user.
RUN terraform version >/dev/null \
    && test -n "$(find "$ECM_TERRAFORM_PLUGIN_DIR" -name '*.zip' -readable)" \
    && test -w /data/clusters \
    && ansible-playbook --version >/dev/null \
    && ansible-runner --version >/dev/null \
    && ssh -V \
    && ansible-galaxy collection list 2>/dev/null | grep -q 'ansible.posix' \
    && ansible-galaxy collection list 2>/dev/null | grep -q 'community.general' \
    && cd "$ECM_ANSIBLE_DIR" \
    && ansible-playbook --syntax-check -i localhost, playbooks/create.yml >/dev/null \
    && ansible-playbook --syntax-check -i localhost, playbooks/converge.yml >/dev/null


# ---- The API and migration image: no Terraform ------------------------------------------------------------
FROM base AS app
USER ecm
