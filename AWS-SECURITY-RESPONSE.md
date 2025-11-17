# AWS Security Incident Response

**Date:** $(date +%Y-%m-%d)
**Incident:** Exposed AWS credentials in public GitHub repository
**Status:** IN PROGRESS

---

## ✅ Actions Completed:

1. **Deactivated Exposed Key** ✅
   - Access Key: `AKIAYW2UULNFAQFSSLXQ`
   - Status: DEACTIVATED
   - Date: 2025-11-14

2. **Git History Cleaned** ✅
   - Removed: `k8s/velero/credentials-velero`
   - Replaced credentials with `***REMOVED***`
   - Force-pushed to GitHub

---

## 🔥 IMMEDIATE ACTIONS REQUIRED:

### Step 1: Create New AWS Access Key ⬜

1. Go to AWS IAM Console: https://console.aws.amazon.com/iam/
2. Navigate to the user that had the exposed key
3. **Security Credentials** tab → **Create access key**
4. Save the new key securely (use AWS Secrets Manager or your Vault)
5. Update applications using the old key:
   - Velero backup configuration
   - Any other S3 access tools
   - Kubernetes secrets
6. Test the new key works
7. **Delete** the old deactivated key: `AKIAYW2UULNFAQFSSLXQ`

---

### Step 2: Check CloudTrail for Unauthorized Activity ⬜

**Critical Period:** Check from when the repo was made public until now

1. Go to CloudTrail Console: https://console.aws.amazon.com/cloudtrail/
2. Click **Event history**
3. Filter by:
   - **User name:** root (or the user with exposed key)
   - **Time range:** Last 24-48 hours
4. Look for suspicious activity:
   - ❌ EC2 instances launched
   - ❌ Lambda functions created
   - ❌ S3 buckets created/accessed
   - ❌ IAM users/roles created
   - ❌ Unusual API calls
   - ❌ Access from unknown IP addresses

**Document any suspicious findings here:**
```
[Add findings]
```

---

### Step 3: Review AWS Resources ⬜

Check each service for unwanted usage:

**EC2:**
- Go to: https://console.aws.amazon.com/ec2/
- Check all regions (top-right dropdown)
- Look for: Unauthorized instances, Spot requests

**Lambda:**
- Go to: https://console.aws.amazon.com/lambda/
- Check all regions
- Look for: Unknown functions

**S3:**
- Go to: https://console.aws.amazon.com/s3/
- Look for: New buckets, unexpected access

**IAM:**
- Go to: https://console.aws.amazon.com/iam/
- Users: Check for unauthorized users
- Roles: Check for unauthorized roles
- Policies: Check for unauthorized policies

**Billing:**
- Go to: https://console.aws.amazon.com/billing/
- Check for unexpected charges

**Document any unwanted resources:**
```
[Add findings]
```

---

### Step 4: Respond to AWS Support Case ⬜

**REQUIRED BY:** 2025-11-19

1. Go to AWS Support Center: https://console.aws.amazon.com/support/
2. Find the existing support case (or create new one)
3. Provide this response:

```
Subject: Security Response - Exposed Access Key AKIAYW2UULNFAQFSSLXQ

Hello AWS Security Team,

I have completed the following security remediation steps:

1. DEACTIVATED the exposed access key: AKIAYW2UULNFAQFSSLXQ
2. CREATED a new access key to replace it
3. DELETED the old deactivated key
4. REMOVED the credentials from the public GitHub repository
5. CLEANED the entire git history to remove all traces
6. REVIEWED CloudTrail logs - [NO UNAUTHORIZED ACTIVITY FOUND / FOUND ACTIVITY - SEE DETAILS]
7. REVIEWED all AWS services across all regions - [NO UNWANTED RESOURCES / FOUND RESOURCES - SEE DETAILS]

The exposed key was committed to a private GitHub repository and was only public for [X hours/days] before detection.

CloudTrail Review Results:
- Date range reviewed: [START] to [END]
- Findings: [DESCRIBE ANY SUSPICIOUS ACTIVITY OR STATE "NONE"]

Resource Review Results:
- Regions checked: ALL
- Findings: [DESCRIBE ANY UNWANTED RESOURCES OR STATE "NONE"]

My account is now secured. Please restore full access to my account.

[IF CHARGES OCCURRED: I request a billing adjustment for any charges incurred from unauthorized usage during this period.]

Thank you,
[Your Name]
```

---

## 📋 Post-Incident Actions:

### Enable MFA (Multi-Factor Authentication) ⬜
1. Go to IAM Console
2. Enable MFA for root account
3. Enable MFA for all IAM users

### Implement Secret Scanning ⬜
- Enable GitHub secret scanning (automatic for public repos)
- Install git-secrets or gitleaks pre-commit hook

### Use AWS Secrets Manager ⬜
- Store future AWS keys in AWS Secrets Manager
- Use IAM roles instead of access keys where possible

### Monitor Going Forward ⬜
- Set up AWS CloudTrail alerts
- Enable AWS Config for compliance monitoring
- Review AWS Trusted Advisor security recommendations

---

## Timeline:

- **2025-11-14 14:42:** Git history cleaned, repo made public
- **2025-11-14 [TIME]:** AWS security alert received
- **2025-11-14 [TIME]:** Access key deactivated
- **2025-11-14 [TIME]:** Git history cleaned again
- **2025-11-14 [TIME]:** Cleaned history force-pushed

---

## Lessons Learned:

1. The initial security scan missed `k8s/velero/credentials-velero`
2. Need more comprehensive secret scanning before public release
3. Should use AWS IAM roles instead of access keys where possible
4. Should store credentials in Vault/Secrets Manager

---

## Checklist Summary:

- ✅ Deactivate exposed key
- ✅ Clean git history
- ✅ Force push to GitHub
- ⬜ Create new access key
- ⬜ Update applications with new key
- ⬜ Delete old key
- ⬜ Review CloudTrail logs
- ⬜ Review AWS resources
- ⬜ Respond to AWS Support
- ⬜ Enable MFA
- ⬜ Implement secret scanning
