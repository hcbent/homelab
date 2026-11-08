import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import App from "./App";
import { duration, OperationDetail, terraformText } from "./OperationDetail";
import { Operations } from "./Operations";
import { mockFetch, posted, table } from "./testing";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
beforeEach(() => { window.location.hash = "#/"; });

const DIGEST = "4d19c465" + "b".repeat(56);
/** The state shown under the title (a step can show the same words, so tests look here for the operation's own). */
const header = () => within(document.querySelector(".ecm-detail__meta") as HTMLElement);
const SUMMARY = { adds: 3, updates: 0, deletes: 0, has_changes: true,
  configure: "install elasticsearch 9.5.6 on 3 nodes and start the cluster" };

function op(over: Record<string, unknown> = {}) {
  return {
    id: "op1", cluster_id: "c1", kind: "tf.create", state: "pending_approval", phase: "approval", error: null,
    elapsed_seconds: 75, started_at: "2026-11-06T18:00:00Z", finished_at: null, dry_run: false, parent_op_id: null,
    progress: { done: 3, total: 6 },
    steps: [
      { seq: 0, name: "render", status: "done", detail: null }, { seq: 1, name: "init", status: "done", detail: null },
      { seq: 2, name: "plan", status: "done", detail: null }, { seq: 3, name: "approval", status: "waiting", detail: null },
      { seq: 4, name: "apply", status: "pending", detail: null }, { seq: 5, name: "configure", status: "pending", detail: null },
    ],
    plan: { digest: DIGEST, summary: SUMMARY, approvable: true }, approval: null, result: null,
    logs: [{ ts: "t", stream: "terraform", line: "Plan: 3 to add, 0 to change, 0 to destroy." }],
    ...over,
  };
}

test("a plan waiting for approval shows what will happen, the digest and the steps", async () => {
  mockFetch(table({ "GET /api/operations/op1": [200, op()] }));
  render(<OperationDetail id="op1" />);
  expect(await screen.findByRole("heading", { name: "Create cluster" })).toBeInTheDocument();
  const plan = screen.getByLabelText("The plan");
  expect(within(plan).getByText("Create 3 virtual machines")).toBeInTheDocument();
  expect(within(plan).getByText("Install elasticsearch 9.5.6 on 3 nodes and start the cluster")).toBeInTheDocument();
  expect(within(plan).getByText(DIGEST)).toBeInTheDocument();
  const steps = screen.getByRole("list", { name: "Steps" });
  expect(within(steps).getByText("Wait for your approval")).toBeInTheDocument();
  expect(within(steps).getByText("waiting for approval")).toBeInTheDocument();
  expect(within(steps).getByText("Install and start Elasticsearch")).toBeInTheDocument();
  expect(header().getByText("waiting for approval")).toBeInTheDocument();
  expect(screen.getByText("Nothing changes until you approve.")).toBeInTheDocument();
});

test("approving asks for confirmation, then sends exactly the digest that was shown", async () => {
  const fn = mockFetch(table({
    "GET /api/operations/op1": [200, op()], "POST /api/operations/op1/approve": [202, { id: "op1" }] }));
  render(<OperationDetail id="op1" />);
  await userEvent.click(await screen.findByRole("button", { name: "Approve and build" }));
  expect(screen.getByText("Approve plan 4d19c465?")).toBeInTheDocument();
  expect(posted(fn, "/api/operations/op1/approve")).toEqual([]);          // nothing is sent before confirming
  await userEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(posted(fn, "/api/operations/op1/approve")).toEqual([{ digest: DIGEST }]));
});

test("a refused approval shows the server's reason and the plan stays", async () => {
  mockFetch(table({
    "GET /api/operations/op1": [200, op()],
    "POST /api/operations/op1/approve": [409, { detail: "the plan changed since you reviewed it" }] }));
  render(<OperationDetail id="op1" />);
  await userEvent.click(await screen.findByRole("button", { name: "Approve and build" }));
  await userEvent.click(screen.getByRole("button", { name: "Approve" }));
  expect(await screen.findByText("the plan changed since you reviewed it")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Approve and build" })).toBeInTheDocument();
});

test("cancelling a plan waiting for approval posts to cancel", async () => {
  const fn = mockFetch(table({
    "GET /api/operations/op1": [200, op()], "POST /api/operations/op1/cancel": [200, { id: "op1" }] }));
  render(<OperationDetail id="op1" />);
  await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(fn.mock.calls.some(([u, i]) => u === "/api/operations/op1/cancel"
    && (i as RequestInit).method === "POST")).toBe(true));
});

test("a dry run says so, shows the plan, and offers no way to approve it", async () => {
  mockFetch(table({ "GET /api/operations/op1": [200, op({
    state: "succeeded", phase: null, dry_run: true, plan: { digest: DIGEST, summary: SUMMARY, approvable: false } })] }));
  render(<OperationDetail id="op1" />);
  expect(await screen.findByText(/This was a dry run: nothing was created/)).toBeInTheDocument();
  expect(screen.getByText("dry run")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
});

test("a failed operation shows its error, keeps the machines in view, and retries on request", async () => {
  const fn = mockFetch(table({
    "GET /api/operations/op1": [200, op({
      state: "failed", phase: "configure", error: "ansible-playbook failed: fatal: [lab-c-01]: FAILED!",
      cluster_id: "c7", progress: { done: 5, total: 6 }, plan: null,
      steps: [{ seq: 4, name: "apply", status: "done", detail: null },
              { seq: 5, name: "configure", status: "failed", detail: "ansible-playbook failed" }] })],
    "POST /api/operations/op1/retry": [202, { id: "op1" }] }));
  render(<OperationDetail id="op1" />);
  const alert = await screen.findByText("This operation failed");
  expect(alert.closest("[role=alert]")).toHaveTextContent("fatal: [lab-c-01]: FAILED!");
  expect(screen.getByRole("link", { name: "open the cluster" })).toHaveAttribute("href", "#/clusters/c7");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(fn.mock.calls.some(([u, i]) => u === "/api/operations/op1/retry"
    && (i as RequestInit).method === "POST")).toBe(true));
});

test("a failed dry run offers no retry, because a dry run starts clean each time", async () => {
  mockFetch(table({ "GET /api/operations/dry": [200, op({ id: "dry", state: "failed", dry_run: true, cluster_id: null,
    error: "terraform init failed", plan: null })] }));
  render(<OperationDetail id="dry" />);
  expect(await screen.findByText("This operation failed")).toBeInTheDocument();
  expect(screen.getByText(/A dry run is not retried/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
});

test("approving a teardown is destructive and needs the start of the digest typed", async () => {
  const fn = mockFetch(table({
    "GET /api/operations/op2": [200, op({ id: "op2", kind: "tf.destroy",
      plan: { digest: DIGEST, summary: { adds: 0, updates: 0, deletes: 3, configure: null }, approvable: true } })],
    "POST /api/operations/op2/approve": [202, { id: "op2" }] }));
  render(<OperationDetail id="op2" />);
  expect(await screen.findByRole("heading", { name: "Tear down cluster" })).toBeInTheDocument();
  expect(screen.getByText("Destroy 3 virtual machines")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Approve and destroy" }));
  const confirm = screen.getByRole("button", { name: "Approve" });
  expect(confirm).toBeDisabled();
  await userEvent.type(screen.getByLabelText(/Type 4d19c465 to confirm/), "4d19c465");
  expect(confirm).toBeEnabled();
  await userEvent.click(confirm);
  await waitFor(() => expect(posted(fn, "/api/operations/op2/approve")).toEqual([{ digest: DIGEST }]));
});

test("a finished teardown says the record is gone, or where to look when it was kept", async () => {
  mockFetch(table({
    "GET /api/operations/gone": [200, op({ id: "gone", kind: "tf.destroy", state: "succeeded", cluster_id: null })],
    "GET /api/operations/kept": [200, op({ id: "kept", kind: "tf.destroy", state: "succeeded", cluster_id: "c7" })] }));
  const { unmount } = render(<OperationDetail id="gone" />);
  expect(await screen.findByText("The cluster is torn down")).toBeInTheDocument();
  expect(screen.getByText(/has removed its record of the cluster; this history stays/)).toBeInTheDocument();
  unmount();
  render(<OperationDetail id="kept" />);
  expect(await screen.findByText(/kept its record because something still blocks removing it/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "open the cluster" })).toHaveAttribute("href", "#/clusters/c7");
});

test("a change to a built cluster is named, approved as a change, and ends with a link back", async () => {
  const fn = mockFetch(table({
    "GET /api/operations/up1": [200, op({ id: "up1", kind: "tf.update", cluster_id: "c1",
      plan: { digest: DIGEST, summary: { adds: 0, updates: 3, deletes: 0,
        configure: "grow the data disk of lab-d-04 to 200 GB and the filesystem on it; nothing restarts" },
        approvable: true } })],
    "POST /api/operations/up1/approve": [202, { id: "up1" }] }));
  render(<OperationDetail id="up1" />);
  expect(await screen.findByRole("heading", { name: "Change cluster" })).toBeInTheDocument();
  expect(screen.getByText("Change 3")).toBeInTheDocument();
  expect(screen.getByText(/Grow the data disk of lab-d-04 to 200 GB/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Approve the change" }));
  await userEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(posted(fn, "/api/operations/up1/approve")).toEqual([{ digest: DIGEST }]));
});

test("a finished change says so and links to the cluster; a failed one says what is kept", async () => {
  mockFetch(table({
    "GET /api/operations/ok": [200, op({ id: "ok", kind: "tf.update", state: "succeeded", cluster_id: "c1", plan: null })],
    "GET /api/operations/bad": [200, op({ id: "bad", kind: "tf.update", state: "failed", cluster_id: "c1", plan: null,
      error: "ansible-playbook failed" })] }));
  const { unmount } = render(<OperationDetail id="ok" />);
  expect(await screen.findByText("The change is applied")).toBeInTheDocument();
  expect(screen.getByText(/come from the last sync/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the cluster" })).toHaveAttribute("href", "#/clusters/c1");
  unmount();
  render(<OperationDetail id="bad" />);
  expect(await screen.findByText(/What Terraform already changed is kept/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("a finished resize says every node has its new size, and a failed one says what is kept", async () => {
  mockFetch(table({ "GET /api/operations/rs": [200, op({ id: "rs", kind: "tf.update", state: "succeeded",
    cluster_id: "c1", plan: null, change: { kind: "resize", describe: "give lab-d-01 8 cores" } })] }));
  render(<OperationDetail id="rs" />);
  expect(await screen.findByText("Every node has its new size")).toBeInTheDocument();
  expect(screen.getByText(/ECM restarted the nodes one at a time/)).toBeInTheDocument();
  expect(screen.queryByText("The change is applied")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the cluster" })).toHaveAttribute("href", "#/clusters/c1");
});

test("a failed resize says every node already restarted stays restarted", async () => {
  mockFetch(table({ "GET /api/operations/rb": [200, op({ id: "rb", kind: "tf.update", state: "failed", cluster_id: "c1",
    plan: null, error: "The rolling restart stopped at lab-d-02", change: { kind: "resize" } })] }));
  render(<OperationDetail id="rb" />);
  expect(await screen.findByText(/and so is every node already restarted/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("an add-nodes plan shows where each new node goes and any placement warning", async () => {
  mockFetch(table({ "GET /api/operations/ad": [200, op({ id: "ad", kind: "tf.update", cluster_id: "c1",
    plan: { digest: DIGEST, approvable: true, summary: { adds: 2, updates: 3, deletes: 0, configure: "add 2 nodes (lab-d-07, lab-d-08)" } },
    change: { kind: "add_node", warnings: ["6 master-eligible nodes is an even number"], nodes: {
      "lab-d-07": { host: "pve1", address: "192.168.10.120", vm_id: 510, roles: "ml", cores: 8, ram_mb: 16384, data_disk_gb: null },
      "lab-d-08": { host: "pve2", address: "192.168.10.121", vm_id: 511, roles: "ml", cores: 8, ram_mb: 16384, data_disk_gb: null } } } })] }));
  render(<OperationDetail id="ad" />);
  expect(await screen.findByText("Where each new node goes", { selector: "h4" })).toBeInTheDocument();
  const row = screen.getByText("lab-d-07").closest("tr")!;
  expect(within(row).getByText("pve1")).toBeInTheDocument();
  expect(within(row).getByText("192.168.10.120")).toBeInTheDocument();
  expect(within(row).getByText("8 cores, 16 GiB")).toBeInTheDocument();                // no data disk, so none is shown
  expect(screen.getByText("6 master-eligible nodes is an even number")).toBeInTheDocument();
});

test("a finished add says only the new nodes were touched, and a failed one says the machines exist", async () => {
  mockFetch(table({
    "GET /api/operations/ok": [200, op({ id: "ok", kind: "tf.update", state: "succeeded", cluster_id: "c1", plan: null,
      change: { kind: "add_node" } })],
    "GET /api/operations/bad": [200, op({ id: "bad", kind: "tf.update", state: "failed", cluster_id: "c1", plan: null,
      error: "The new nodes did not all join: lab-d-07", change: { kind: "add_node" } })] }));
  const { unmount } = render(<OperationDetail id="ok" />);
  expect(await screen.findByText("The new nodes joined the cluster")).toBeInTheDocument();
  expect(screen.getByText(/The existing nodes were not touched/)).toBeInTheDocument();
  expect(screen.queryByText("The change is applied")).not.toBeInTheDocument();
  unmount();
  render(<OperationDetail id="bad" />);
  expect(await screen.findByText(/so the new machines exist. Retry configures them again, which is safe to repeat/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

const REMOVAL = { kind: "remove_nodes", warnings: ["lab-d-07 is the elected master, so a new master is elected when it goes (a few seconds)"],
  nodes: {
    "lab-d-07": { host: "pve1", address: "192.168.10.120", vm_id: 510, roles: "data, ingest", cores: 4, ram_mb: 8192, data_disk_gb: 100,
      shards: 3, data_bytes: 5 * 1024 ** 3 },
    "lab-d-08": { host: "pve2", address: "192.168.10.121", vm_id: 511, roles: "none (coordinating only)", cores: 2, ram_mb: 4096,
      data_disk_gb: null, shards: 0, data_bytes: 0 } } };
const REMOVE_STEPS = ["render", "init", "plan", "approval", "drain", "apply", "configure"].map((name, seq) => ({
  seq, name, status: seq < 3 ? "done" : seq === 3 ? "waiting" : "pending", detail: null }));

test("a removal plan lists the nodes it destroys with the data that must move, and asks to approve and remove", async () => {
  mockFetch(table({ "GET /api/operations/rm": [200, op({ id: "rm", kind: "tf.update", cluster_id: "c1", steps: REMOVE_STEPS,
    plan: { digest: DIGEST, approvable: true, summary: { adds: 0, updates: 0, deletes: 2,
      configure: "remove 2 nodes (lab-d-07, lab-d-08)" } }, change: REMOVAL })] }));
  render(<OperationDetail id="rm" />);
  expect(await screen.findByText("The nodes this removes", { selector: "h4" })).toBeInTheDocument();
  expect(screen.getByText("Move the data off the nodes")).toBeInTheDocument();             // the new step, in plain words
  const row = screen.getByText("lab-d-07").closest("tr")!;
  expect(within(row).getByText("pve1")).toBeInTheDocument();
  expect(within(row).getByText("3 shards, 5.0 GB")).toBeInTheDocument();
  expect(within(screen.getByText("lab-d-08").closest("tr")!).getByText("none")).toBeInTheDocument();
  expect(screen.getByText(/lab-d-07 is the elected master/)).toBeInTheDocument();
  expect(screen.getByText("Destroy 2 virtual machines")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Approve and remove" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/Elasticsearch moves the data off the nodes first. Then destroy 2 virtual machines/)).toBeInTheDocument();
});

test("a removal that failed at the drain says nothing was destroyed, and a later failure says the machines are gone", async () => {
  const drainFailed = REMOVE_STEPS.map((s) => ({ ...s, status: s.name === "drain" ? "failed" : s.seq < 4 ? "done" : "pending" }));
  const configureFailed = REMOVE_STEPS.map((s) => ({ ...s, status: s.name === "configure" ? "failed" : s.seq < 6 ? "done" : "pending" }));
  mockFetch(table({
    "GET /api/operations/d": [200, op({ id: "d", kind: "tf.update", state: "failed", cluster_id: "c1", plan: null,
      steps: drainFailed, error: "Elasticsearch could not empty every node", change: REMOVAL })],
    "GET /api/operations/c": [200, op({ id: "c", kind: "tf.update", state: "failed", cluster_id: "c1", plan: null,
      steps: configureFailed, error: "the cluster was not green", change: REMOVAL })] }));
  const { unmount } = render(<OperationDetail id="d" />);
  expect(await screen.findByText(/Nothing was destroyed: the data is moved off the nodes first/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  unmount();
  render(<OperationDetail id="c" />);
  expect(await screen.findByText(/Once the machines were destroyed they stay gone/)).toBeInTheDocument();
});

test("a finished removal says the data was moved, the machines destroyed and the cluster is green", async () => {
  mockFetch(table({ "GET /api/operations/ok": [200, op({ id: "ok", kind: "tf.update", state: "succeeded", cluster_id: "c1",
    plan: null, change: REMOVAL })] }));
  render(<OperationDetail id="ok" />);
  expect(await screen.findByText("The nodes are removed")).toBeInTheDocument();
  expect(screen.getByText(/moved the data off them, Terraform destroyed their machines/)).toBeInTheDocument();
  expect(screen.queryByText("The change is applied")).not.toBeInTheDocument();
});

const RECOVERY_NODES = { "lab-d-04": { host: "pve2", address: "192.168.10.113", vm_id: 503, roles: "data, ingest", cores: 4,
  ram_mb: 8192, data_disk_gb: 100, moved: true } };
const APPLY_STEPS = ["render", "init", "plan", "approval", "apply", "configure"].map((name, seq) => ({
  seq, name, status: seq < 3 ? "done" : seq === 3 ? "waiting" : "pending", detail: null }));

test("a rebuild plan lists the lost nodes with where each goes, and asks to approve and rebuild", async () => {
  mockFetch(table({ "GET /api/operations/rb": [200, op({ id: "rb", kind: "tf.update", cluster_id: "c1", steps: APPLY_STEPS,
    plan: { digest: DIGEST, approvable: true, summary: { adds: 1, updates: 0, deletes: 0, configure: "rebuild 1 lost node (lab-d-04)" } },
    change: { kind: "rebuild_nodes", warnings: ["lab-d-04 goes to pve2, not pve3 where it was"], nodes: RECOVERY_NODES } })] }));
  render(<OperationDetail id="rb" />);
  expect(await screen.findByText("The nodes this rebuilds", { selector: "h4" })).toBeInTheDocument();
  const row = screen.getByText("lab-d-04").closest("tr")!;
  expect(within(row).getByText("pve2")).toBeInTheDocument();
  expect(within(row).getByText("4 cores, 8 GiB, 100 GB data")).toBeInTheDocument();
  expect(screen.getByText("lab-d-04 goes to pve2, not pve3 where it was")).toBeInTheDocument();
  expect(screen.getByText("Create 1 virtual machine")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Approve and rebuild" })).toBeInTheDocument();
});

test("a forget plan says nothing happens on Proxmox, lists the nodes, and still asks for an approval", async () => {
  mockFetch(table({ "GET /api/operations/fg": [200, op({ id: "fg", kind: "tf.update", cluster_id: "c1", steps: APPLY_STEPS,
    plan: { digest: DIGEST, approvable: true, summary: { adds: 0, updates: 0, deletes: 0, has_changes: false,
      configure: "forget 1 lost node (lab-d-04)" } },
    change: { kind: "forget_nodes", warnings: [], nodes: RECOVERY_NODES } })] }));
  render(<OperationDetail id="fg" />);
  expect(await screen.findByText("The lost nodes this forgets", { selector: "h4" })).toBeInTheDocument();
  expect(screen.getByText("Nothing: the machines are already gone")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Approve and forget" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/Nothing is destroyed: the machines are already gone/)).toBeInTheDocument();
});

test("finished and failed recovery operations say what was and was not changed", async () => {
  mockFetch(table({
    "GET /api/operations/r1": [200, op({ id: "r1", kind: "tf.update", state: "succeeded", cluster_id: "c1", plan: null,
      change: { kind: "rebuild_nodes", nodes: RECOVERY_NODES } })],
    "GET /api/operations/r2": [200, op({ id: "r2", kind: "tf.update", state: "failed", cluster_id: "c1", plan: null,
      error: "The new nodes did not all join", change: { kind: "rebuild_nodes", nodes: RECOVERY_NODES } })],
    "GET /api/operations/f1": [200, op({ id: "f1", kind: "tf.update", state: "succeeded", cluster_id: "c1", plan: null,
      change: { kind: "forget_nodes", nodes: RECOVERY_NODES } })],
    "GET /api/operations/f2": [200, op({ id: "f2", kind: "tf.update", state: "failed", cluster_id: "c1", plan: null,
      error: "x", change: { kind: "forget_nodes", nodes: RECOVERY_NODES } })] }));
  let view = render(<OperationDetail id="r1" />);
  expect(await screen.findByText("The rebuilt nodes joined the cluster")).toBeInTheDocument();
  expect(screen.getByText(/empty disks fill from the others/)).toBeInTheDocument();
  view.unmount();
  view = render(<OperationDetail id="r2" />);
  expect(await screen.findByText(/the rebuilt machines exist. Retry configures them again/)).toBeInTheDocument();
  view.unmount();
  view = render(<OperationDetail id="f1" />);
  expect(await screen.findByText("The lost nodes are forgotten")).toBeInTheDocument();
  view.unmount();
  render(<OperationDetail id="f2" />);
  expect(await screen.findByText(/Nothing was destroyed, because the machines were already gone/)).toBeInTheDocument();
  expect(screen.queryByText("The change is applied")).not.toBeInTheDocument();
});

const RESTART_CHANGE = { kind: "restart_nodes", order: ["lab-d-04", "lab-d-05", "lab-d-01"],
  warnings: ["lab-d-05 holds the only copy of 1 shard (solo[0]); those indices are unavailable while it restarts"],
  nodes: {
    "lab-d-04": { action: "start", host: "pve1", vm_id: 503, roles: "data", position: 1 },
    "lab-d-05": { action: "restart", host: "pve2", vm_id: 504, roles: "data", position: 2 },
    "lab-d-01": { action: "restart", host: "pve1", vm_id: 500, roles: "master", position: 3 } } };
const RESTART_STEPS = ["plan", "approval", "restart"].map((name, seq) => ({
  seq, name, status: seq < 1 ? "done" : seq === 1 ? "waiting" : "pending", detail: null }));

test("a restart plan shows the order, what happens to each node and the warnings, and asks to approve and restart", async () => {
  mockFetch(table({ "GET /api/operations/rs": [200, op({ id: "rs", kind: "es.restart", cluster_id: "c1", steps: RESTART_STEPS,
    plan: { digest: DIGEST, approvable: true, summary: { restart: 2, start: 1, has_changes: true,
      configure: "restart 3 nodes one at a time (lab-d-04, lab-d-05, lab-d-01)" } }, change: RESTART_CHANGE })] }));
  render(<OperationDetail id="rs" />);
  expect(await screen.findByRole("heading", { name: "Restart nodes" })).toBeInTheDocument();
  expect(screen.getByText("The order the nodes go in", { selector: "h4" })).toBeInTheDocument();
  expect(screen.getByText("Restart the nodes one at a time")).toBeInTheDocument();         // the step, in plain words
  expect(screen.getByText("Restart 2 nodes and start 1 node that is down")).toBeInTheDocument();
  const first = screen.getByText("lab-d-04").closest("tr")!;
  expect(within(first).getByText("Started (it is not in the cluster)")).toBeInTheDocument();
  expect(within(screen.getByText("lab-d-01").closest("tr")!).getByText("Restarted")).toBeInTheDocument();
  expect(screen.getByText(/lab-d-05 holds the only copy of 1 shard/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Approve and restart" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/Each node is briefly out of the cluster, and ECM waits for the cluster to be green before each/)).toBeInTheDocument();
});

test("a restart that failed says what stays done, and a finished one says the cluster is green", async () => {
  mockFetch(table({
    "GET /api/operations/bad": [200, op({ id: "bad", kind: "es.restart", state: "failed", cluster_id: "c1", plan: null, steps: RESTART_STEPS,
      error: "The restart stopped at lab-d-05: the node did not come back", change: RESTART_CHANGE })],
    "GET /api/operations/ok": [200, op({ id: "ok", kind: "es.restart", state: "succeeded", cluster_id: "c1", plan: null, steps: RESTART_STEPS,
      change: RESTART_CHANGE })] }));
  const { unmount } = render(<OperationDetail id="bad" />);
  expect(await screen.findByText(/Nodes already restarted stay restarted. Retry plans again and needs a new approval/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  unmount();
  render(<OperationDetail id="ok" />);
  expect(await screen.findByText("The nodes are restarted")).toBeInTheDocument();
  expect(screen.queryByText("The change is applied")).not.toBeInTheDocument();
});

const manyLines = (n: number) => Array.from({ length: n }, (_, i) => ({ ts: "t", stream: i % 2 ? "ansible" : "terraform", line: `line ${i + 1}` }));

test("Copy log copies every line, including the ones the window does not draw, and says how many", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  mockFetch(table({ "GET /api/operations/big": [200, op({ id: "big", state: "succeeded", plan: null, logs: manyLines(450) })] }));
  render(<OperationDetail id="big" />);
  expect(await screen.findByText(/50 earlier lines are not shown/)).toBeInTheDocument();            // the window draws the last 400
  await userEvent.click(screen.getByRole("button", { name: "Copy log" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
  const text: string = writeText.mock.calls[0][0];
  expect(text.split("\n")).toHaveLength(450);
  expect(text.startsWith("[terraform] line 1\n[ansible] line 2")).toBe(true);                     // a line that is not on the screen
  expect(text.endsWith("[ansible] line 450")).toBe(true);
  expect(await screen.findByRole("status")).toHaveTextContent("Copied 450 lines");
});

test("Copy log falls back to the old copy command when the clipboard API is not there, and says when it cannot copy at all", async () => {
  Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
  const exec = vi.fn(() => true);
  Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
  mockFetch(table({ "GET /api/operations/one": [200, op({ id: "one", state: "succeeded", plan: null, logs: manyLines(1) })] }));
  const { unmount } = render(<OperationDetail id="one" />);
  await userEvent.click(await screen.findByRole("button", { name: "Copy log" }));
  expect(exec).toHaveBeenCalledWith("copy");
  expect(await screen.findByRole("status")).toHaveTextContent("Copied 1 line");                      // singular
  expect(document.querySelector("textarea")).toBeNull();                                          // the helper box is removed
  unmount();

  Object.defineProperty(document, "execCommand", { value: vi.fn(() => false), configurable: true });
  render(<OperationDetail id="one" />);
  await userEvent.click(await screen.findByRole("button", { name: "Copy log" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Could not copy the log");
});

test("an operation with no log lines has nothing to copy", async () => {
  mockFetch(table({ "GET /api/operations/none": [200, op({ id: "none", plan: null, state: "running", phase: "plan", logs: [] })] }));
  render(<OperationDetail id="none" />);
  expect(await screen.findByRole("button", { name: "Copy log" })).toBeDisabled();
});

test("a finished create links to the cluster and the log keeps its stream labels", async () => {
  mockFetch(table({ "GET /api/operations/op1": [200, op({
    state: "succeeded", phase: null, plan: null, progress: { done: 6, total: 6 },
    result: { configured: { cluster_uuid: "u1", status: "green", number_of_nodes: 3 } },
    logs: [{ ts: "t", stream: "ansible", line: "TASK [es_node : Write elasticsearch.yml]" }] })] }));
  render(<OperationDetail id="op1" />);
  expect(await screen.findByText("The cluster is up")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the cluster" })).toHaveAttribute("href", "#/clusters/c1");
  expect(screen.getByLabelText("Operation log")).toHaveTextContent("[ansible] TASK [es_node : Write elasticsearch.yml]");
  expect(screen.getByText(/Secrets are redacted/)).toBeInTheDocument();
});

test("a running operation is polled until it finishes", async () => {
  let calls = 0;
  const fn = mockFetch((url) => {
    calls += 1;
    return [200, op(calls < 2 ? { state: "running", phase: "apply", plan: null }
      : { state: "succeeded", phase: null, plan: null, progress: { done: 6, total: 6 } })];
  });
  render(<OperationDetail id="op1" />);
  await screen.findByRole("heading", { name: "Create cluster" });
  expect(header().getByText("running")).toBeInTheDocument();
  await waitFor(() => expect(header().getByText("succeeded")).toBeInTheDocument(), { timeout: 4000 });
  const settled = fn.mock.calls.length;
  await new Promise((r) => setTimeout(r, 2300));
  expect(fn.mock.calls.length).toBe(settled);                              // polling stopped at a final state
}, 12000);

test("an operation that cannot be loaded says why and can be retried", async () => {
  mockFetch(table({ "GET /api/operations/op9": [404, { detail: "Operation not found" }] }));
  render(<OperationDetail id="op9" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Operation not found");
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("helpers say durations and Terraform plans in plain words", () => {
  expect(duration(null)).toBe("—");
  expect(duration(59)).toBe("59s");
  expect(duration(125)).toBe("2m 5s");
  expect(terraformText("tf.create", { adds: 1 })).toBe("Create 1 virtual machine");
  expect(terraformText("tf.create", { adds: 3, deletes: 1 })).toBe("Create 3 virtual machines, destroy 1 virtual machine");
  expect(terraformText("tf.destroy", { adds: 0, deletes: 0 })).toBe("Nothing left to destroy");
  expect(terraformText("tf.create", { adds: 0 })).toBe("No changes");
  expect(terraformText("tf.create", null)).toBe("No plan yet");
});

test("the operations list links each operation to its detail and marks dry runs", async () => {
  mockFetch(table({ "GET /api/operations": [200, [
    { id: "op1", kind: "tf.create", state: "succeeded", phase: null, elapsed_seconds: 12, error: null, dry_run: true,
      cluster_id: "c1", parent_op_id: null }]] }));
  render(<Operations />);
  await userEvent.click(await screen.findByRole("switch", { name: "Show dry runs (1)" }));   // hidden until asked for
  expect(await screen.findByRole("link", { name: "Open details" })).toHaveAttribute("href", "#/operations/op1");
  expect(screen.getByText("dry run")).toBeInTheDocument();
});

test("an operation's own page opens from the hash, with a way back", async () => {
  window.location.hash = "#/operations/op1";
  mockFetch(table({
    "GET /api/auth/me": [200, { username: "admin", role: "admin" }], "GET /api/operations/op1": [200, op()] }));
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Create cluster" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "All operations" })).toHaveAttribute("href", "#/operations");
  expect(screen.getByRole("link", { name: "Operations" })).toHaveAttribute("aria-current", "page");
});
