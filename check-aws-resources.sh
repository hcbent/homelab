#!/bin/bash
# Check for unauthorized AWS resources across all regions

echo "🔍 Checking AWS resources across all regions..."
echo ""

# Get all available regions
REGIONS=$(aws ec2 describe-regions --query 'Regions[*].RegionName' --output text)

echo "Regions to check: $(echo $REGIONS | wc -w)"
echo ""

# Check EC2 instances
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Checking EC2 Instances..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for region in $REGIONS; do
    instances=$(aws ec2 describe-instances \
        --region "$region" \
        --query 'Reservations[*].Instances[*].[InstanceId,State.Name,InstanceType,LaunchTime]' \
        --output text 2>/dev/null)

    if [ -n "$instances" ]; then
        echo "Region: $region"
        echo "$instances"
        echo ""
    fi
done

# Check Lambda functions
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Checking Lambda Functions..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for region in $REGIONS; do
    functions=$(aws lambda list-functions \
        --region "$region" \
        --query 'Functions[*].[FunctionName,Runtime,LastModified]' \
        --output text 2>/dev/null)

    if [ -n "$functions" ]; then
        echo "Region: $region"
        echo "$functions"
        echo ""
    fi
done

# Check S3 buckets (global)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Checking S3 Buckets..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
aws s3 ls

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Checking IAM Users..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
aws iam list-users --query 'Users[*].[UserName,CreateDate]' --output table

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Checking IAM Roles (created in last 7 days)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SEVEN_DAYS_AGO=$(date -u -v-7d +%Y-%m-%d)
aws iam list-roles --query "Roles[?CreateDate>='$SEVEN_DAYS_AGO'].[RoleName,CreateDate]" --output table

echo ""
echo "✅ Resource check complete!"
echo ""
echo "Review all resources above and verify they are legitimate."
echo "Delete any unauthorized resources immediately."
