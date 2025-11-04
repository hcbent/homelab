# Contributing to Homelab Infrastructure

Thank you for your interest in contributing to this homelab infrastructure project! This guide will help you understand how to contribute effectively.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Workflow](#development-workflow)
3. [Code Style](#code-style)
4. [Testing](#testing)
5. [Pull Request Process](#pull-request-process)
6. [Issue Guidelines](#issue-guidelines)
7. [Code of Conduct](#code-of-conduct)

## Getting Started

### Prerequisites

Before contributing, ensure you have:

1. **Required Tools**:
   - Terraform >= 1.5.0
   - Ansible >= 2.15.0
   - kubectl >= 1.28.0
   - vault CLI >= 1.15.0
   - git >= 2.30.0
   - Pre-commit hooks (recommended)

2. **Development Environment**:
   - Access to a test environment (Proxmox cluster recommended but not required)
   - HashiCorp Vault instance for testing
   - Understanding of Infrastructure-as-Code principles

3. **Knowledge Requirements**:
   - Familiarity with Terraform, Ansible, or Kubernetes (depending on contribution area)
   - Understanding of homelab infrastructure concepts
   - Basic Git workflow knowledge

### Setting Up Your Development Environment

1. **Fork and Clone**:
   ```bash
   # Fork the repository on GitHub
   git clone https://github.com/YOUR_USERNAME/homelab.git
   cd homelab
   git remote add upstream https://github.com/ORIGINAL_OWNER/homelab.git
   ```

2. **Install Dependencies**:
   ```bash
   # Install Terraform
   brew install terraform  # macOS
   # OR
   apt install terraform   # Ubuntu

   # Install Ansible
   brew install ansible    # macOS
   # OR
   apt install ansible     # Ubuntu

   # Install Vault CLI
   brew install vault      # macOS
   # OR
   apt install vault       # Ubuntu

   # Install pre-commit hooks
   pip install pre-commit
   pre-commit install
   ```

3. **Set Up Vault (for testing)**:
   ```bash
   # Follow the Vault setup guide
   # See: docs/VAULT-SETUP.md
   ```

4. **Create Configuration Files**:
   ```bash
   # Copy example files
   find . -name "*.example" | while read f; do
     cp "$f" "${f%.example}"
   done

   # Edit with test values (never use production credentials)
   ```

## Development Workflow

### Branch Strategy

- **main**: Stable, production-ready code
- **feature/**: New features or enhancements
- **fix/**: Bug fixes
- **docs/**: Documentation updates

### Creating a Feature Branch

```bash
# Update your fork
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/your-feature-name

# Or for bug fixes
git checkout -b fix/issue-description
```

### Commit Message Conventions

We follow conventional commit format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks
- `ci`: CI/CD changes

**Examples**:
```bash
feat(terraform): add support for additional Proxmox node

fix(ansible): correct vault password lookup path

docs(readme): update deployment instructions

refactor(k8s): simplify ArgoCD application structure
```

### Making Changes

1. **Make Small, Focused Changes**:
   - One logical change per commit
   - Keep PRs focused on a single feature/fix
   - Separate refactoring from functional changes

2. **Test Your Changes**:
   ```bash
   # Terraform
   cd tf/your-module
   terraform fmt
   terraform validate
   terraform plan

   # Ansible
   cd ansible
   ansible-lint playbooks/your-playbook.yml
   ansible-playbook --syntax-check playbooks/your-playbook.yml

   # Kubernetes
   kubectl apply --dry-run=client -f k8s/your-manifest.yaml
   ```

3. **Run Pre-commit Hooks**:
   ```bash
   pre-commit run --all-files
   ```

4. **Commit Your Changes**:
   ```bash
   git add .
   git commit -m "feat(scope): description of change"
   ```

## Code Style

### Terraform

**Formatting**:
```hcl
# Use terraform fmt
terraform fmt -recursive

# Variable naming: snake_case
variable "vm_name" {
  type = string
}

# Resource naming: service_resource_name
resource "proxmox_vm_qemu" "k8s_control_plane" {
  name = "kube01"
}

# Use for_each for multiple similar resources
resource "proxmox_vm_qemu" "workers" {
  for_each = toset(var.worker_names)
  name     = each.key
}
```

**Best Practices**:
- Use variables for all environment-specific values
- Never hardcode secrets (use Vault data sources)
- Add descriptions to all variables and outputs
- Mark sensitive outputs with `sensitive = true`
- Use modules for reusable components

### Ansible

**Formatting**:
```yaml
---
# Use YAML best practices
- name: Configure application
  hosts: all
  become: true

  tasks:
    - name: Install package (descriptive task names)
      ansible.builtin.apt:
        name: nginx
        state: present
      tags:
        - packages
        - nginx

    - name: Copy configuration
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        mode: '0644'
      notify: Reload nginx
      no_log: true  # For tasks handling secrets
```

**Best Practices**:
- Use fully qualified collection names (FQCNs)
- Add `no_log: true` for tasks handling secrets
- Use tags for selective execution
- Use Vault lookups instead of hardcoded secrets
- Prefer `ansible.builtin` modules over deprecated alternatives

### Kubernetes

**Formatting**:
```yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-name
  namespace: namespace-name
  labels:
    app: app-name
    version: v1.0.0
spec:
  replicas: 3
  selector:
    matchLabels:
      app: app-name
  template:
    metadata:
      labels:
        app: app-name
    spec:
      containers:
        - name: app
          image: app:1.0.0
          env:
            - name: SECRET_VALUE
              valueFrom:
                secretKeyRef:
                  name: app-secrets
                  key: secret-key
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "200m"
```

**Best Practices**:
- Use External Secrets Operator for secret management
- Always specify resource requests and limits
- Use namespace isolation
- Add labels for organization
- Use liveness and readiness probes

### Shell Scripts

**Formatting**:
```bash
#!/bin/bash
set -euo pipefail

# Script description
# Usage: script.sh [options]

# Constants
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly VAULT_ADDR="https://192.168.10.101:8200"

# Functions
function main() {
  echo "Starting process..."
  # Implementation
}

# Error handling
function error_exit() {
  echo "ERROR: $1" >&2
  exit 1
}

# Main execution
main "$@"
```

**Best Practices**:
- Use `set -euo pipefail` for error handling
- Quote all variables
- Use functions for organization
- Add usage documentation
- Use colored output for user feedback (see existing scripts)

## Testing

### Terraform Testing

```bash
# Format check
terraform fmt -check -recursive

# Validation
terraform init
terraform validate

# Plan (with test values)
terraform plan -var-file=test.tfvars

# Security scan (optional)
tfsec .
```

### Ansible Testing

```bash
# Syntax check
ansible-playbook --syntax-check playbooks/your-playbook.yml

# Lint
ansible-lint playbooks/your-playbook.yml

# Dry run
ansible-playbook -i inventory/test --check playbooks/your-playbook.yml

# Molecule tests (if applicable)
molecule test
```

### Kubernetes Testing

```bash
# Validate YAML
kubectl apply --dry-run=client -f manifest.yaml

# Validate against cluster
kubectl apply --dry-run=server -f manifest.yaml

# Lint
kubeval manifest.yaml

# Test in test namespace
kubectl apply -f manifest.yaml -n test
```

### Secret Scanning

```bash
# Scan for secrets before committing
gitleaks protect --verbose

# Scan entire repository
gitleaks detect --source . --verbose
```

## Pull Request Process

### Before Creating a PR

1. **Update Your Branch**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Test Your Changes**:
   - Run all relevant tests
   - Verify in test environment if possible
   - Check for no secrets in code

3. **Update Documentation**:
   - Update README.md if adding features
   - Add/update .example files for new configurations
   - Update relevant docs in `docs/` directory

### Creating the PR

1. **Push Your Branch**:
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Create Pull Request** on GitHub with:
   - **Title**: Following conventional commit format
   - **Description**:
     - What changes were made
     - Why the changes are needed
     - How to test the changes
     - Related issues (if any)

3. **PR Template**:
   ```markdown
   ## Description
   Brief description of changes

   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Documentation update
   - [ ] Refactoring

   ## Testing
   - [ ] Terraform validated
   - [ ] Ansible syntax checked
   - [ ] No secrets in code
   - [ ] Documentation updated

   ## Checklist
   - [ ] Code follows project style
   - [ ] Tests pass
   - [ ] Documentation updated
   - [ ] .example files created/updated
   ```

### PR Review Process

1. **Automated Checks**:
   - Secret scanning (Phase 2)
   - Terraform validation (Phase 2)
   - Linting

2. **Manual Review**:
   - Code quality
   - Security considerations
   - Documentation completeness
   - Test coverage

3. **Addressing Feedback**:
   ```bash
   # Make requested changes
   git add .
   git commit -m "fix: address review feedback"
   git push origin feature/your-feature-name
   ```

4. **Merge Requirements**:
   - All checks passing
   - At least one approval
   - No merge conflicts
   - Up to date with main

## Issue Guidelines

### Reporting Bugs

Use the bug report template:

```markdown
**Description**
Clear description of the bug

**Steps to Reproduce**
1. Step one
2. Step two
3. See error

**Expected Behavior**
What should happen

**Actual Behavior**
What actually happens

**Environment**
- OS: [e.g., Ubuntu 22.04]
- Terraform version:
- Ansible version:
- Other relevant info:

**Additional Context**
Any other context about the problem
```

### Requesting Features

Use the feature request template:

```markdown
**Feature Description**
Clear description of the proposed feature

**Use Case**
Why is this feature needed?

**Proposed Solution**
How should this be implemented?

**Alternatives Considered**
Other approaches you've considered

**Additional Context**
Any other context or screenshots
```

### Security Issues

**DO NOT** create public issues for security vulnerabilities.

See [SECURITY.md](SECURITY.md#vulnerability-reporting) for reporting process.

## Code of Conduct

### Our Standards

**Positive Behaviors**:
- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what's best for the community
- Showing empathy towards others

**Unacceptable Behaviors**:
- Trolling, insulting, or derogatory comments
- Public or private harassment
- Publishing others' private information
- Other conduct that's unprofessional

### Enforcement

Violations may result in:
1. Warning
2. Temporary ban
3. Permanent ban

Report violations to repository maintainers.

## Development Tips

### Testing Without Production Environment

If you don't have a full homelab setup:

1. **Terraform**: Use `terraform plan` to validate syntax
2. **Ansible**: Use `--check` mode for dry runs
3. **Kubernetes**: Use `kubectl --dry-run` for validation
4. **Documentation**: Anyone can contribute documentation improvements

### Documentation Contributions

Documentation improvements are always welcome:
- Fix typos and grammar
- Improve clarity
- Add examples
- Update outdated information
- Add troubleshooting tips

### Small Contributions Matter

Don't hesitate to contribute small improvements:
- Fixing a typo
- Improving a comment
- Adding a missing .example file
- Updating a dependency version

## Getting Help

If you need help:

1. **Check Documentation**:
   - [README.md](../README.md)
   - [docs/](.) directory

2. **Search Issues**:
   - Check if your question was already asked

3. **Ask Questions**:
   - Create a new issue with the "question" label
   - Be specific about what you need help with

## Recognition

Contributors will be:
- Listed in commit history
- Acknowledged in release notes (for significant contributions)
- Appreciated for making this project better

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (see LICENSE file).

## Related Documentation

- [Deployment Guide](DEPLOYMENT-GUIDE.md) - Complete deployment workflow
- [Security Best Practices](SECURITY.md) - Security guidelines
- [Secret Management](SECRET-MANAGEMENT.md) - Vault usage patterns
- [Vault Setup](VAULT-SETUP.md) - Vault installation and configuration

## Thank You!

Thank you for taking the time to contribute to this project. Every contribution, no matter how small, helps make this infrastructure better for everyone.
