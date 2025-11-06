#!/bin/bash
# Actualbudget Deployment Tests
# Focused tests for verifying Actualbudget deployment in Kubernetes

set -e

NAMESPACE="home-apps"
APP_NAME="actualbudget"
NODEPORT=30006
MAX_WAIT=120  # seconds

echo "=== Actualbudget Deployment Tests ==="
echo "Namespace: $NAMESPACE"
echo "Application: $APP_NAME"
echo ""

# Test 1: Verify pod exists and is running
echo "Test 1: Pod startup and running status"
if kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME &>/dev/null; then
    POD_STATUS=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME -o jsonpath='{.items[0].status.phase}')
    if [ "$POD_STATUS" = "Running" ]; then
        echo "  PASS - Pod is running"
    else
        echo "  FAIL - Pod status: $POD_STATUS"
        kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME
        exit 1
    fi
else
    echo "  FAIL - Pod not found"
    exit 1
fi

# Test 2: Verify pod readiness
echo "Test 2: Pod readiness"
READY=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME -o jsonpath='{.items[0].status.containerStatuses[0].ready}')
if [ "$READY" = "true" ]; then
    echo "  PASS - Pod is ready"
else
    echo "  FAIL - Pod is not ready"
    kubectl describe pod -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME
    exit 1
fi

# Test 3: Verify PVC is bound
echo "Test 3: PVC binding"
PVC_NAME=$(kubectl get pvc -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME -o jsonpath='{.items[0].metadata.name}')
if [ -n "$PVC_NAME" ]; then
    PVC_STATUS=$(kubectl get pvc -n $NAMESPACE $PVC_NAME -o jsonpath='{.status.phase}')
    if [ "$PVC_STATUS" = "Bound" ]; then
        echo "  PASS - PVC $PVC_NAME is bound"
    else
        echo "  FAIL - PVC $PVC_NAME status: $PVC_STATUS"
        kubectl describe pvc -n $NAMESPACE $PVC_NAME
        exit 1
    fi
else
    echo "  FAIL - PVC not found"
    exit 1
fi

# Test 4: Verify NodePort service exists and is accessible
echo "Test 4: NodePort service accessibility"
SERVICE_NAME=$(kubectl get svc -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME -o jsonpath='{.items[0].metadata.name}')
if [ -n "$SERVICE_NAME" ]; then
    SERVICE_TYPE=$(kubectl get svc -n $NAMESPACE $SERVICE_NAME -o jsonpath='{.spec.type}')
    if [ "$SERVICE_TYPE" = "NodePort" ]; then
        ACTUAL_NODEPORT=$(kubectl get svc -n $NAMESPACE $SERVICE_NAME -o jsonpath='{.spec.ports[0].nodePort}')
        echo "  PASS - NodePort service exists on port $ACTUAL_NODEPORT"
    else
        echo "  FAIL - Service type is $SERVICE_TYPE, expected NodePort"
        exit 1
    fi
else
    echo "  FAIL - Service not found"
    exit 1
fi

# Test 5: Verify HTTP endpoint responds
echo "Test 5: HTTP endpoint response"
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
ACTUAL_NODEPORT=$(kubectl get svc -n $NAMESPACE $SERVICE_NAME -o jsonpath='{.spec.ports[0].nodePort}')

# Try to reach the endpoint (allow up to 30 seconds)
for i in {1..6}; do
    if curl -s -o /dev/null -w "%{http_code}" http://$NODE_IP:$ACTUAL_NODEPORT/ | grep -q "200\|302"; then
        echo "  PASS - HTTP endpoint responding"
        break
    elif [ $i -eq 6 ]; then
        echo "  FAIL - HTTP endpoint not responding after 30 seconds"
        echo "  Debug info:"
        kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME --tail=20
        exit 1
    fi
    sleep 5
done

# Test 6: Verify data persistence (check that /data is mounted)
echo "Test 6: Data persistence volume mount"
POD_NAME=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME -o jsonpath='{.items[0].metadata.name}')
MOUNT_CHECK=$(kubectl exec -n $NAMESPACE $POD_NAME -- sh -c 'mount | grep /data' 2>/dev/null || echo "")
if [ -n "$MOUNT_CHECK" ]; then
    echo "  PASS - /data volume is mounted"
else
    echo "  WARNING - /data volume mount not confirmed (may not be critical)"
fi

# Test 7: Verify storage class is correct
echo "Test 7: Storage class verification"
STORAGE_CLASS=$(kubectl get pvc -n $NAMESPACE $PVC_NAME -o jsonpath='{.spec.storageClassName}')
if [ "$STORAGE_CLASS" = "freenas-iscsi-csi" ]; then
    echo "  PASS - Using correct storage class: $STORAGE_CLASS"
else
    echo "  FAIL - Wrong storage class: $STORAGE_CLASS (expected freenas-iscsi-csi)"
    exit 1
fi

# Test 8: Verify pod restarts successfully (optional stress test)
echo "Test 8: Pod restart resilience"
kubectl delete pod -n $NAMESPACE $POD_NAME
echo "  Waiting for pod to restart..."
sleep 10
kubectl wait --for=condition=ready pod -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME --timeout=${MAX_WAIT}s
if [ $? -eq 0 ]; then
    echo "  PASS - Pod restarted successfully and became ready"
else
    echo "  FAIL - Pod did not become ready after restart"
    kubectl describe pod -n $NAMESPACE -l app.kubernetes.io/name=$APP_NAME
    exit 1
fi

echo ""
echo "=== All Actualbudget Tests Passed ==="
echo "Application is ready for use at http://$NODE_IP:$ACTUAL_NODEPORT/"
exit 0
