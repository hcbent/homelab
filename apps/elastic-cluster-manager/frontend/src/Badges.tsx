const HEALTH: Record<string, string> = {
  green: "bg-green-100 text-green-800", yellow: "bg-yellow-100 text-yellow-800",
  red: "bg-red-100 text-red-800",
};
const LINK: Record<string, string> = {
  verified: "bg-green-100 text-green-800", probable: "bg-yellow-100 text-yellow-800",
  unlinked: "bg-slate-100 text-slate-700",
};

export const HealthBadge = ({ status }: { status: string | null }) => (
  <span className={`rounded px-2 py-0.5 text-xs font-medium ${HEALTH[status ?? ""] ?? "bg-slate-100"}`}>
    {status ?? "unknown"}
  </span>
);

export const LinkBadge = ({ confidence }: { confidence: string }) => (
  <span title={confidence === "probable" ? "Name match only; not trusted for ownership" : undefined}
    className={`rounded px-2 py-0.5 text-xs ${LINK[confidence]}`}>{confidence}</span>
);

export const OwnershipBadge = ({ value }: { value: string }) => (
  <span className="rounded border px-2 py-0.5 text-xs">{value}</span>
);
