import { EuiBadge, EuiHealth } from "@elastic/eui";

// Status is always a dot plus a text label, never colour alone.
const HEALTH: Record<string, string> = { green: "success", yellow: "warning", red: "danger" };
const LINK: Record<string, string> = { verified: "success", probable: "warning", unlinked: "subdued" };

export const HealthBadge = ({ status }: { status: string | null }) => (
  <EuiHealth color={HEALTH[status ?? ""] ?? "subdued"}>{status ?? "unknown"}</EuiHealth>
);

export const LinkBadge = ({ confidence }: { confidence: string }) => (
  <div title={confidence === "probable" ? "Name match only; not trusted for ownership" : undefined}>
    <EuiHealth color={LINK[confidence] ?? "subdued"}>{confidence}</EuiHealth>
  </div>
);

export const OwnershipBadge = ({ value }: { value: string }) => (
  <EuiBadge color="hollow">{value}</EuiBadge>
);
