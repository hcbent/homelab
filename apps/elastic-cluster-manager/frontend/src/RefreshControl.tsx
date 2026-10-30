import { store } from "./format";

export function RefreshControl({ seconds, onChange, onNow }:
  { seconds: number; onChange: (s: number) => void; onNow: () => void }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <label>Auto-refresh
        <select className="ml-1 rounded border p-1" value={seconds}
          onChange={(e) => { const v = Number(e.target.value); store("ecm.refresh", v); onChange(v); }}>
          <option value={0}>off</option><option value={10}>10s</option><option value={30}>30s</option>
          <option value={60}>1m</option><option value={300}>5m</option>
        </select>
      </label>
      <button className="rounded border px-2 py-1" onClick={onNow}>Refresh</button>
    </div>
  );
}
