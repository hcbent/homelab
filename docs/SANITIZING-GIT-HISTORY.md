# Git History Sanitization Guide

This guide explains how to remove sensitive data from your Git repository history before making it public.

## Table of Contents

1. [Overview](#overview)
2. [Why Sanitize](#why-sanitize)
3. [What is git-filter-repo](#what-is-git-filter-repo)
4. [Risks and Considerations](#risks-and-considerations)
5. [Automated Approach](#automated-approach)
6. [Manual Approach](#manual-approach)
7. [Verification](#verification)
8. [Rollback Procedures](#rollback-procedures)
9. [After Sanitization](#after-sanitization)

## Overview

**Git history sanitization** is the process of permanently removing sensitive files and data from your entire Git history, including all branches, tags, and commits. This is essential before making a private repository public.

## Why Sanitize

Even after deleting files from your current working directory, they remain accessible in Git history:

```bash
# File deleted in current branch
ls CCHS_PASSWORD  # File not found

# But accessible in history
git log --all -- CCHS_PASSWORD  # Shows all commits with this file
git show HEAD~5:CCHS_PASSWORD   # Can still read file contents from old commits
```

**Making a repository public without sanitization exposes**:
- All historical versions of deleted files
- Secrets that were committed and later removed
- Sensitive data from any point in repository history

## What is git-filter-repo

`git-filter-repo` is the recommended tool for rewriting Git history (replacing the deprecated `git-filter-branch`).

### Features
- **Fast**: 10-50x faster than git-filter-branch
- **Safe**: Built-in safety checks and analysis
- **Powerful**: Can filter by paths, content, authors, and more
- **Maintained**: Actively developed and officially recommended by Git

### Installation

```bash
# macOS
brew install git-filter-repo

# Ubuntu/Debian
pip3 install git-filter-repo

# Manual installation
git clone https://github.com/newren/git-filter-repo.git
sudo cp git-filter-repo/git-filter-repo /usr/local/bin/
```

Verify installation:
```bash
git-filter-repo --version
```

## Risks and Considerations

**⚠️ WARNING**: Git history rewriting is **IRREVERSIBLE** and has significant consequences:

### What Changes
- **All commit hashes change** - Every commit gets a new SHA-1
- **Entire history is rewritten** - All branches, tags, and refs are modified
- **Old clones become incompatible** - Anyone with existing clones must re-clone

### Coordination Required
- **Notify all contributors** before sanitizing
- **Choose a maintenance window** when no one is working
- **Communicate the timeline** for re-cloning
- **Backup everything** before starting

### Cannot Be Undone
Once you force-push sanitized history to remote:
- Old history is permanently overwritten
- Previous commit references become invalid
- Old branches cannot be merged

## Automated Approach

We provide a script that automates the sanitization process with safety checks.

### Using the Sanitization Script

#### Dry-Run Mode (Recommended First)

Preview what will be removed without making changes:

```bash
cd homelab
./scripts/sanitize-git-history.sh --dry-run
```

Output shows:
- Files that will be removed
- Current repository statistics
- No actual changes are made

#### Full Sanitization

After reviewing dry-run output:

```bash
./scripts/sanitize-git-history.sh
```

The script will:
1. **Create backup branch**: `backup/pre-sanitization-TIMESTAMP`
2. **Verify prerequisites**: Check for git-filter-repo
3. **Show what will be removed**: List all targeted files
4. **Require explicit confirmation**: Type "YES" to proceed
5. **Remove files from history**: Execute git-filter-repo
6. **Run validation checks**: Verify files are removed
7. **Generate analysis report**: Save results to `~/.git-sanitization-*.txt`

### Files Automatically Removed

The script removes:
- **Explicit files**: CCHS_PASSWORD, makerspace_es_api_key, ansible/inventory/vault
- **Deleted files**: ELASTIC_PASSWORD, MONITORING_PASSWORD, vault/README.md
- **Pattern-based**: *_PASSWORD, *_TOKEN, *_API_KEY, *_SECRET files
- **Environment files**: .env files (preserving *.env.example)
- **Key files**: *.pem, *.key files (preserving *.pub)
- **Vault files**: *vault-init*.json, vault-init*.txt

### Script Safety Features

- **Backup creation**: Automatic backup branch before any changes
- **Dry-run mode**: Preview without modification
- **Confirmation prompts**: Require explicit "YES" to proceed
- **Validation checks**: Post-sanitization verification
- **Analysis reporting**: Detailed log of what was removed
- **Rollback guidance**: Instructions for reverting if needed

## Manual Approach

For those who prefer manual control or need custom filtering:

### Step 1: Backup Current State

Create a backup branch:

```bash
git branch backup/pre-sanitization-$(date +%Y%m%d_%H%M%S)
```

### Step 2: Create Paths File

Create a file listing paths to remove:

```bash
cat > /tmp/filter-paths.txt <<EOF
CCHS_PASSWORD
makerspace_es_api_key
ansible/inventory/vault
ELASTIC_PASSWORD
MONITORING_PASSWORD
k8s/helm/values/freenas-nfs.yaml
k8s/helm/values/freenas-iscsi.yaml
vault/README.md
EOF
```

### Step 3: Run git-filter-repo

Remove files from entire history:

```bash
git filter-repo --invert-paths --paths-from-file /tmp/filter-paths.txt --force
```

Options explained:
- `--invert-paths`: Remove specified paths (instead of keeping only them)
- `--paths-from-file`: Read paths from file
- `--force`: Required if .git/config has remote URLs

### Step 4: Remove Pattern-Based Files

For glob patterns, use separate commands:

```bash
# Remove all *_PASSWORD files
git filter-repo --invert-paths --path-glob '*_PASSWORD' --force

# Remove all *_TOKEN files
git filter-repo --invert-paths --path-glob '*_TOKEN' --force

# Remove all *_API_KEY files
git filter-repo --invert-paths --path-glob '*_API_KEY' --force
```

### Step 5: Verify Changes

```bash
# Check specific file is gone
git log --all -- CCHS_PASSWORD

# List all remaining files
git ls-files

# Check repository size
du -sh .git
```

## Verification

After sanitization, thoroughly verify the results:

### 1. File-Specific Checks

Verify each sensitive file is removed:

```bash
# Should return empty
git log --all --format=%H -- CCHS_PASSWORD
git log --all --format=%H -- makerspace_es_api_key
git log --all --format=%H -- ansible/inventory/vault

# Verify current state
ls -la CCHS_PASSWORD  # Should not exist
git status           # Should show no deleted files
```

### 2. Content Search

Search for secret patterns in history:

```bash
# Search for specific strings
git log --all -S"api_key=" --format=%H
git log --all -S"password=" --format=%H
git log --all -S"root@192.168" --format=%H

# Search for base64-encoded secrets (if applicable)
git log --all -S"eyJhbGci" --format=%H
```

### 3. Automated Secret Scanning

Use gitleaks to scan for secrets:

```bash
# Install gitleaks
brew install gitleaks

# Scan entire history
gitleaks detect --source . --verbose --no-git

# Check specific branches
gitleaks detect --source . --log-level debug
```

### 4. Repository Statistics

Compare before and after:

```bash
# Commit count (should remain same)
git rev-list --all --count

# Repository size (should decrease)
du -sh .git

# File count
git ls-files | wc -l
```

### 5. Manual History Review

Review recent history manually:

```bash
# Last 50 commits
git log --all --oneline -50

# Check specific branches
git log main --oneline
git log develop --oneline

# View file tree at different points
git ls-tree -r HEAD
git ls-tree -r HEAD~10
```

## Rollback Procedures

If you discover issues after sanitization, you can restore from backup:

### Option 1: Reset to Backup Branch

If you haven't pushed yet:

```bash
# Find your backup branch
git branch | grep backup/pre-sanitization

# Reset to backup (DESTRUCTIVE)
git reset --hard backup/pre-sanitization-20231104_143022

# Delete the backup branch
git branch -D backup/pre-sanitization-20231104_143022
```

### Option 2: Re-clone from Remote

If you have a remote backup:

```bash
# Rename current directory
mv homelab homelab-sanitized-backup

# Clone fresh from remote
git clone git@github.com:username/homelab.git

# Verify it has original history
cd homelab
git log --all -- CCHS_PASSWORD  # Should show old commits
```

### Option 3: Restore from Local Backup

If you created a separate backup:

```bash
# Remove sanitized repository
rm -rf homelab

# Restore from backup
cp -r homelab-backup homelab
cd homelab

# Verify restoration
git log --all -- CCHS_PASSWORD
```

## After Sanitization

### 1. Verify Remote Status

Before pushing:

```bash
# Check remote configuration
git remote -v

# Verify you're on correct branch
git branch

# Check status
git status
```

### 2. Force Push (DANGEROUS)

**⚠️ This overwrites remote history permanently!**

```bash
# Dry-run first
git push --force --dry-run origin main

# Push all branches
git push --force --all origin

# Push tags
git push --force --tags origin
```

### 3. Notify Contributors

Send this message to all contributors:

```
Subject: URGENT: Repository History Rewritten

The homelab repository history has been sanitized to remove sensitive data.

ACTION REQUIRED:
1. Delete your local clone: rm -rf homelab
2. Clone fresh copy: git clone <repo-url>
3. Re-create any local branches from main
4. DO NOT push old branches

Old clones are incompatible and must be discarded.

Contact me if you have uncommitted work that needs to be preserved.
```

### 4. Update CI/CD

If you have CI/CD pipelines:
- Clear build caches
- Retrigger failed builds
- Update webhook registrations if needed

### 5. GitHub/GitLab Settings

On GitHub:
- Go to Settings → Branches
- Temporarily remove branch protection
- Force push
- Re-enable branch protection
- Clear any cached data

### 6. Final Verification

After force push:

```bash
# Fresh clone
git clone <repo-url> homelab-verify
cd homelab-verify

# Verify secrets are gone
git log --all -- CCHS_PASSWORD
gitleaks detect --source . --verbose
```

### 7. Monitor Repository

For the next few weeks:
- Watch for secret scanning alerts
- Monitor commit history for reintroduced secrets
- Ensure contributors are using new clones

## Advanced Topics

### Rewriting Author Information

If commits contain sensitive email addresses:

```bash
git filter-repo --mailmap mailmap.txt --force
```

Where `mailmap.txt` contains:

```
Public Name <public@example.com> Private Name <private@company.com>
```

### Removing Large Files

If you also want to remove large binary files:

```bash
# Find large files
git rev-list --objects --all | \
  git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | \
  awk '/^blob/ {print substr($0,6)}' | \
  sort --numeric-sort --key=2 | \
  tail -n 10

# Remove specific large file
git filter-repo --path large-file.bin --invert-paths --force
```

### Preserving Specific Commits

To remove files but preserve specific commits:

```bash
# Create list of commits to preserve
git log --format=%H -- important.txt > commits-to-keep.txt

# Filter with commit preservation
git filter-repo --invert-paths --path CCHS_PASSWORD --refs-file commits-to-keep.txt --force
```

## Best Practices

1. **Test First**: Always run dry-run mode before actual sanitization
2. **Backup Everything**: Create multiple backups before starting
3. **Verify Thoroughly**: Use multiple verification methods
4. **Communicate Clearly**: Notify all team members with detailed instructions
5. **Schedule Appropriately**: Choose low-activity time for sanitization
6. **Document Process**: Keep notes of what was done and why
7. **Monitor After**: Watch for any issues in the days following

## Common Issues

### Issue: git-filter-repo fails with "remote URLs detected"

**Solution**: Use `--force` flag:
```bash
git filter-repo --invert-paths --path FILE --force
```

### Issue: Repository size hasn't decreased

**Solution**: Run garbage collection:
```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### Issue: Some secrets still appear in history

**Solution**: Re-run with additional patterns:
```bash
git filter-repo --invert-paths --path-glob '*secret*' --force
```

### Issue: Contributors can't push after sanitization

**Solution**: They must delete and re-clone:
```bash
rm -rf old-repo
git clone <repo-url>
```

## Security Notes

- **Assume Compromise**: If secrets were ever pushed, consider them exposed
- **Rotate Credentials**: Change all exposed passwords and keys
- **GitHub Still Caches**: Contact GitHub support to clear cached views
- **Search Engines**: Cached pages may still show old content
- **Forks and Mirrors**: Won't be affected; must sanitize separately

## References

- [git-filter-repo Documentation](https://github.com/newren/git-filter-repo)
- [GitHub: Removing Sensitive Data](https://docs.github.com/en/github/authenticating-to-github/removing-sensitive-data-from-a-repository)
- [Git SCM: Rewriting History](https://git-scm.com/book/en/v2/Git-Tools-Rewriting-History)
- [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/) (alternative tool)

## Next Steps

After successfully sanitizing your Git history:

1. Update all credentials that were exposed (see [Credential Rotation](../vault/scripts/04-rotate-credentials.sh))
2. Configure secret scanning to prevent future commits (see [Security Guide](SECURITY.md))
3. Set up pre-commit hooks (see [Contributing Guide](CONTRIBUTING.md))
4. Review and update .gitignore to prevent re-introduction
5. Make repository public only after thorough verification
