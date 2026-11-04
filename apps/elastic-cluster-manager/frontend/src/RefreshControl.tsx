import { EuiButton, EuiSelect } from "@elastic/eui";
import { store } from "./format";

const OPTIONS = [
  { value: 0, text: "off" }, { value: 10, text: "10s" }, { value: 30, text: "30s" },
  { value: 60, text: "1m" }, { value: 300, text: "5m" },
];

export function RefreshControl({ seconds, onChange, onNow }:
  { seconds: number; onChange: (s: number) => void; onNow: () => void }) {
  return (
    <div className="ecm-refresh">
      <EuiSelect aria-label="Auto-refresh" prepend="Auto-refresh" options={OPTIONS} value={seconds}
        onChange={(e) => { const v = Number(e.target.value); store("ecm.refresh", v); onChange(v); }} />
      <EuiButton iconType="refresh" onClick={onNow}>Refresh</EuiButton>
    </div>
  );
}
