import { EuiIcon, EuiPanel, EuiSkeletonRectangle } from "@elastic/eui";
import { CSSProperties, ReactNode } from "react";

/**
 * The summary stat tile: accent-tinted icon seat, large numeral, tracked uppercase label and one line of context.
 * The surface stays neutral; status colour only ever appears on the health indicator next to the numeral.
 */
export function StatTile({ icon, label, value, description, health, index = 0, loading = false }: {
  icon: string; label: string; value: ReactNode; description: ReactNode; health?: ReactNode;
  index?: number; loading?: boolean;
}) {
  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="none" borderRadius="m" className="ecm-tile ecm-enter"
      style={{ "--i": index } as CSSProperties} aria-busy={loading || undefined}>
      <span className="ecm-seat" aria-hidden="true"><EuiIcon type={icon} size="l" /></span>
      <div className="ecm-tile__body">
        <div className="ecm-tile__value">
          {loading ? <EuiSkeletonRectangle width={72} height={38} borderRadius="s" /> : (
            <>
              <span className="ecm-numeral">{value}</span>
              {health}
            </>
          )}
        </div>
        <p className="ecm-label">{label}</p>
        {loading ? <EuiSkeletonRectangle width="90%" height={18} borderRadius="s" />
          : <p className="ecm-tile__desc">{description}</p>}
      </div>
    </EuiPanel>
  );
}
