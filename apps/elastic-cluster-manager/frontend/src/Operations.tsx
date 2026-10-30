import { useEffect, useState } from "react";
import { api, Operation } from "./api";

export function Operations() {
  const [ops, setOps] = useState<Operation[]>([]);
  const load = () => api<Operation[]>("/api/operations").then(setOps).catch(() => {});

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  async function runDemo() {
    await api("/api/operations/demo", { method: "POST" });
    load();
  }

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-medium">Operations</h2>
        <button onClick={runDemo} className="rounded border px-3 py-1 text-sm">
          Run demo job
        </button>
      </div>
      <table className="w-full text-left text-sm">
        <thead><tr><th>Kind</th><th>State</th><th>Phase</th><th>Elapsed</th></tr></thead>
        <tbody>
          {ops.map((o) => (
            <tr key={o.id}>
              <td>{o.kind}</td><td>{o.state}</td><td>{o.phase ?? "—"}</td>
              <td>{o.elapsed_seconds ?? "—"}s</td>
            </tr>
          ))}
        </tbody>
      </table>
      {ops.length === 0 && <p className="mt-2 text-sm text-slate-500">No operations yet.</p>}
    </section>
  );
}
