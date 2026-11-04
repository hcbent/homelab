import { EuiConfirmModal, EuiFieldText, EuiFormRow, EuiText } from "@elastic/eui";
import { useState } from "react";

/**
 * Lifecycle confirmation foundation for Phase 4. It always names the resource, and a destructive
 * action stays disabled until the operator types that resource name. Nothing here calls the API.
 */
export function ConfirmAction({ action, resource, destructive = false, onConfirm, onCancel }: {
  action: string; resource: string; destructive?: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  const [typed, setTyped] = useState("");
  const blocked = destructive && typed !== resource;
  return (
    <EuiConfirmModal title={`${action} ${resource}?`} onCancel={onCancel} onConfirm={onConfirm}
      cancelButtonText="Cancel" confirmButtonText={action} buttonColor={destructive ? "danger" : "primary"}
      confirmButtonDisabled={blocked} defaultFocusedButton="cancel">
      <EuiText size="s"><p>This acts on <strong className="ecm-mono">{resource}</strong>.</p></EuiText>
      {destructive && (
        <EuiFormRow label={`Type ${resource} to confirm`} fullWidth>
          <EuiFieldText fullWidth value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </EuiFormRow>)}
    </EuiConfirmModal>
  );
}
