#!/bin/bash
# Quick CloudTrail check for unauthorized activity
# This checks for suspicious API calls using the exposed credentials

echo "🔍 Checking CloudTrail for unauthorized activity..."
echo "Looking for activity from exposed key: AKIAYW2UULNFAQFSSLXQ"
echo ""

# Set time range (last 7 days to be safe)
START_TIME=$(date -u -v-7d +"%Y-%m-%dT%H:%M:%S")
END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S")

echo "Time range: $START_TIME to $END_TIME"
echo ""

# Check for EC2 instances launched
echo "Checking for EC2 instances launched..."
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=RunInstances \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --max-results 50 \
  --query 'Events[*].[EventTime,Username,EventName,Resources]' \
  --output table

echo ""
echo "Checking for IAM user/role creation..."
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateUser \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --max-results 50 \
  --query 'Events[*].[EventTime,Username,EventName]' \
  --output table

echo ""
echo "Checking for Lambda function creation..."
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateFunction \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --max-results 50 \
  --query 'Events[*].[EventTime,Username,EventName]' \
  --output table

echo ""
echo "Checking for S3 bucket creation..."
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateBucket \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --max-results 50 \
  --query 'Events[*].[EventTime,Username,EventName,Resources]' \
  --output table

echo ""
echo "✅ CloudTrail check complete!"
echo ""
echo "Review the output above for any suspicious activity."
echo "If you see any events you didn't initiate, document them immediately."
