# Security Best Practices for Homelab

**Last Updated:** 2025-11-14

This document outlines security best practices learned from the AWS credential exposure incident.

---

## 🔐 Prevent Future Secret Leaks

### 1. Install Pre-commit Secret Scanning

Install `gitleaks` to catch secrets before they're committed:

```bash
# Install gitleaks
brew install gitleaks

# Initialize in your repo
cd /Users/bret/git/homelab
gitleaks protect --staged --verbose

# Add to pre-commit hook
cat > .git/hooks/pre-commit <<'EOF'
#!/bin/bash
gitleaks protect --staged --verbose
if [ $? -ne 0 ]; then
    echo "❌ Gitleaks detected secrets in staged files!"
    echo "Remove secrets and try again."
    exit 1
fi
EOF

chmod +x .git/hooks/pre-commit
```

### 2. Regular Secret Scanning

Run periodic scans on your entire repository:

```bash
# Scan entire repository
gitleaks detect --verbose

# Scan git history
gitleaks detect --verbose --log-opts="--all"
```

### 3. Use GitHub Secret Scanning

For public repos, GitHub automatically scans for secrets:
- Enabled automatically for public repositories
- Partner patterns (AWS, Azure, etc.) trigger alerts
- Check: https://github.com/hcbent/homelab/settings/security_analysis

---

## 🔑 Credential Management

### Use Secrets Management Tools

**Never commit plaintext secrets.** Use these instead:

#### Option 1: HashiCorp Vault (You already have this!)
```bash
# Store secrets in Vault
vault kv put secret/aws/backup \
  access_key_id="YOUR_KEY" \
  secret_access_key="YOUR_SECRET"

# Retrieve in scripts
export AWS_ACCESS_KEY_ID=$(vault kv get -field=access_key_id secret/aws/backup)
export AWS_SECRET_ACCESS_KEY=$(vault kv get -field=secret_access_key secret/aws/backup)
```

#### Option 2: External Secrets Operator (Kubernetes)
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: aws-credentials
spec:
  secretStoreRef:
    name: vault-backend
  target:
    name: aws-creds-secret
  data:
  - secretKey: access_key_id
    remoteRef:
      key: secret/aws/backup
      property: access_key_id
```

#### Option 3: AWS IAM Roles (Preferred for AWS)
Instead of access keys, use IAM roles:
- For EC2: Attach IAM role to instance
- For EKS: Use IRSA (IAM Roles for Service Accounts)
- For Lambda: Execution roles

### Always Use .example Files

For configuration files that need secrets:

```bash
# Create template
cp k8s/velero/credentials-velero k8s/velero/credentials-velero.example

# Sanitize the example
sed -i '' 's/AKIAYW2UULNF.*/CHANGEME_AWS_ACCESS_KEY/' k8s/velero/credentials-velero.example
sed -i '' 's/[A-Za-z0-9/+=]{40}/CHANGEME_AWS_SECRET_KEY/' k8s/velero/credentials-velero.example

# Add real file to .gitignore
echo "k8s/velero/credentials-velero" >> .gitignore

# Commit only the .example
git add k8s/velero/credentials-velero.example .gitignore
git commit -m "Add velero credentials template"
```

---

## 🛡️ AWS Security Hardening

### Enable MFA (Multi-Factor Authentication)

**For Root Account:**
1. Go to: https://console.aws.amazon.com/iam/
2. Click "Activate MFA" on root account
3. Use authenticator app (Authy, Google Authenticator)

**For IAM Users:**
```bash
# Enable MFA for IAM user
aws iam create-virtual-mfa-device --virtual-mfa-device-name $USERNAME-mfa
aws iam enable-mfa-device --user-name $USERNAME --serial-number $ARN
```

### Use IAM Policies Wisely

**Principle of Least Privilege:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-backup-bucket",
        "arn:aws:s3:::my-backup-bucket/*"
      ]
    }
  ]
}
```

### Enable CloudTrail Logging

```bash
# Create CloudTrail
aws cloudtrail create-trail \
  --name homelab-audit \
  --s3-bucket-name my-cloudtrail-logs

# Enable logging
aws cloudtrail start-logging --name homelab-audit

# Enable log file validation
aws cloudtrail update-trail \
  --name homelab-audit \
  --enable-log-file-validation
```

### Set Up Billing Alerts

```bash
# Enable billing alerts
aws ce create-anomaly-monitor \
  --monitor-name "Unusual-Spending-Monitor" \
  --monitor-type DIMENSIONAL

# Set budget
aws budgets create-budget \
  --account-id YOUR_ACCOUNT_ID \
  --budget file://budget.json
```

---

## 📊 Monitoring & Alerts

### AWS CloudWatch Alarms

Set up alerts for suspicious activity:

```bash
# Alert on unauthorized API calls
aws cloudwatch put-metric-alarm \
  --alarm-name UnauthorizedAPICalls \
  --alarm-description "Alert on unauthorized API calls" \
  --metric-name UnauthorizedAPICalls \
  --namespace AWS/CloudTrail \
  --statistic Sum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 1
```

### GitHub Security Alerts

Enable on your repository:
1. Go to: https://github.com/hcbent/homelab/settings/security_analysis
2. Enable:
   - Dependabot alerts
   - Dependabot security updates
   - Secret scanning (auto-enabled for public)
   - Code scanning

---

## 🔄 Regular Security Maintenance

### Weekly Tasks
- [ ] Review AWS CloudTrail logs for unusual activity
- [ ] Check AWS billing for unexpected charges
- [ ] Scan repository for new secrets: `gitleaks detect`

### Monthly Tasks
- [ ] Review and rotate service account credentials
- [ ] Update dependencies (Renovate is already doing this!)
- [ ] Review IAM users and remove unused accounts
- [ ] Review S3 bucket policies and access logs

### Quarterly Tasks
- [ ] Rotate AWS access keys
- [ ] Review and update .gitignore patterns
- [ ] Audit all credentials stored in Vault
- [ ] Review and update IAM policies
- [ ] Test disaster recovery procedures

---

## 📚 Additional Resources

### Tools
- **gitleaks**: https://github.com/gitleaks/gitleaks
- **git-secrets**: https://github.com/awslabs/git-secrets
- **truffleHog**: https://github.com/trufflesecurity/trufflehog
- **detect-secrets**: https://github.com/Yelp/detect-secrets

### Documentation
- AWS Security Best Practices: https://aws.amazon.com/security/best-practices/
- GitHub Secret Scanning: https://docs.github.com/en/code-security/secret-scanning
- Vault Best Practices: https://developer.hashicorp.com/vault/tutorials/best-practices

### Incident Response
- AWS Incident Response: https://aws.amazon.com/premiumsupport/technology/trusted-advisor/
- What to do if compromised: https://aws.amazon.com/premiumsupport/knowledge-center/potential-account-compromise/

---

## ✅ Security Checklist

Current status for this repository:

- ✅ All secrets removed from git history
- ✅ Comprehensive .gitignore patterns implemented
- ✅ `.example` templates created for sensitive files
- ✅ AWS credentials rotated
- ⬜ Pre-commit hooks installed (gitleaks)
- ⬜ MFA enabled on AWS account
- ⬜ CloudTrail logging enabled
- ⬜ Billing alerts configured
- ⬜ Regular security scanning scheduled

---

**Remember:** Security is an ongoing process, not a one-time task. Stay vigilant!
