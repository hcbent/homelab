import {
  EuiBadge, EuiBasicTable, EuiBasicTableColumn, EuiButton, EuiCallOut, EuiHealth, EuiLink, EuiLoadingSpinner, EuiPanel,
} from "@elastic/eui";
import { useEffect, useState } from "react";
import { api, ApiError, ClusterDetail, Operation } from "./api";
import { ConfirmAction } from "./ConfirmAction";
import { ago } from "./format";
import { KIND } from "./OperationDetail";

const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

/**
 * Tear down or remove a cluster ECM built. What is offered comes from the API's `lifecycle`, which reads the same
 * rules the endpoints enforce. A teardown only makes a plan: the destroy happens when it is approved on the
 * operation page, which asks for the plan's digest again.
 */
export function ClusterLifecycle({ cluster }: { cluster: ClusterDetail }) {
  const life = cluster.lifecycle;
  const [asking, setAsking] = useState<"teardown" | "remove" | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!life?.managed) return null;
  const nodes = life.nodes ?? [];

  async function confirm(kind: "teardown" | "remove") {
    setAsking(null);
    setError(null);
    try {
      if (kind === "teardown") {
        const op = await api<{ id: string }>(`/api/operations/${life!.teardown_of}/cleanup`, {
          method: "POST", body: JSON.stringify({ confirm_name: cluster.name, confirm_data_loss: Boolean(life!.bootstrapped) }),
        });
        window.location.hash = `#/operations/${op.id}`;
      } else {
        await api(`/api/clusters/${cluster.id}/remove`, { method: "POST", body: JSON.stringify({ confirm_name: cluster.name }) });
        window.location.hash = "#/";
      }
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-lifecycle"
      aria-labelledby="lifecycle-title">
      <h3 id="lifecycle-title" className="ecm-h3">Tear down or remove</h3>
      {error && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That did not work" size="s">
          <p>{error}</p></EuiCallOut>)}

      {life.busy_operation_id ? (
        <EuiCallOut color="primary" iconType="info" size="s" title="An operation is running on this cluster">
          <p>Wait for it to finish before tearing the cluster down or removing it.{" "}
            <EuiLink href={`#/operations/${life.busy_operation_id}`}>Open it</EuiLink></p></EuiCallOut>
      ) : life.teardown_of ? (
        <>
          <p>Tearing down plans a destroy of {nodes.length || "its"} virtual machine{nodes.length === 1 ? "" : "s"}
            {nodes.length > 0 && <>: <span className="ecm-mono">{nodes.join(", ")}</span></>}. You review the plan and
            approve it on the next screen. Nothing is destroyed before you approve.</p>
          {life.bootstrapped && (
            <EuiCallOut color="warning" iconType="warning" size="s" title="Elasticsearch is running on these machines">
              <p>Any data in the cluster is destroyed with them.</p></EuiCallOut>)}
          <div><EuiButton color="danger" iconType="trash" onClick={() => setAsking("teardown")}>Tear down cluster</EuiButton></div>
        </>
      ) : life.can_remove ? (
        <>
          <p>The machines are gone. Removing ECM's record of this cluster clears it from the list. The history of
            its operations is kept.</p>
          <div><EuiButton color="danger" onClick={() => setAsking("remove")}>Remove record</EuiButton></div>
        </>
      ) : <p className="ecm-muted">{life.remove_blocker
        ? `This cluster cannot be removed yet: ${life.remove_blocker}.`
        : "There is nothing to tear down or remove right now."}</p>}

      {asking === "teardown" && (
        <ConfirmAction action="Tear down" confirmText="Plan the teardown" resource={cluster.name} destructive
          onCancel={() => setAsking(null)} onConfirm={() => confirm("teardown")}>
          <p>ECM will plan a destroy of {nodes.length} virtual machine{nodes.length === 1 ? "" : "s"} and show it
            to you. This step changes nothing yet.{life.bootstrapped ? " Data in the cluster is lost once you approve it." : ""}</p>
        </ConfirmAction>)}
      {asking === "remove" && (
        <ConfirmAction action="Remove" resource={cluster.name} destructive onCancel={() => setAsking(null)}
          onConfirm={() => confirm("remove")}>
          <p>This removes ECM's record of the cluster and any credentials it stored for it. It touches no machines.</p>
        </ConfirmAction>)}
    </EuiPanel>
  );
}

const STATE_COLOR: Record<string, string> = {
  succeeded: "success", failed: "danger", running: "primary", pending_approval: "warning", cancelled: "subdued",
};

/** The operations that acted on this cluster, newest first. */
export function ClusterOperations({ clusterId }: { clusterId: string }) {
  const [ops, setOps] = useState<Operation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Operation[]>("/api/operations").then((all) => setOps(all.filter((o) => o.cluster_id === clusterId)))
      .catch((e) => setError(message(e)));
  }, [clusterId]);

  if (error) return <EuiCallOut color="danger" role="alert" iconType="warning" title="Could not load operations"><p>{error}</p></EuiCallOut>;
  if (!ops) return <p role="status"><EuiLoadingSpinner size="m" /> Loading operations…</p>;
  const columns: EuiBasicTableColumn<Operation>[] = [
    { name: "Operation", render: (o: Operation) => (
      <><EuiLink href={`#/operations/${o.id}`}>{KIND[o.kind] ?? o.kind}</EuiLink>{" "}
        {o.dry_run && <EuiBadge color="hollow">dry run</EuiBadge>}</>) },
    { name: "State", render: (o: Operation) => (
      <EuiHealth color={STATE_COLOR[o.state] ?? "subdued"}>{o.state.replace("pending_approval", "waiting for approval")}</EuiHealth>) },
    { name: "Started", render: (o: Operation) => ago(o.started_at ?? null) },
  ];
  return <EuiBasicTable<Operation> tableCaption="Operations on this cluster" items={ops} columns={columns}
    noItemsMessage="No operation has acted on this cluster yet." />;
}
