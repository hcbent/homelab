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

test("a finished resize says the new size is set but the machines have not restarted", async () => {
  mockFetch(table({ "GET /api/operations/rs": [200, op({ id: "rs", kind: "tf.update", state: "succeeded",
    cluster_id: "c1", plan: null, change: { kind: "resize", describe: "give lab-d-01 8 cores" } })] }));
  render(<OperationDetail id="rs" />);
  expect(await screen.findByText(/The new size is set in Proxmox, and the machines have not restarted/)).toBeInTheDocument();
  expect(screen.getByText(/which ECM does not do for you yet/)).toBeInTheDocument();
  expect(screen.queryByText("The change is applied")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the cluster" })).toHaveAttribute("href", "#/clusters/c1");
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
