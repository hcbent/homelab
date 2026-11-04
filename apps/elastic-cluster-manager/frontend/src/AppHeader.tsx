import {
  EuiButtonEmpty, EuiButtonIcon, EuiHeader, EuiHeaderLink, EuiHeaderLinks, EuiHeaderSection, EuiHeaderSectionItem,
  useIsWithinBreakpoints,
} from "@elastic/eui";
import { useThemeMode } from "./theme";

export const NAV = [
  { label: "Clusters", href: "#/" },
  { label: "Infrastructure", href: "#/infrastructure" },
  { label: "Operations", href: "#/operations" },
  { label: "Help", href: "#/help" },
];

/** True when the current hash belongs to the nav item (cluster detail belongs to Clusters). */
export function isActive(href: string, hash: string) {
  if (href === "#/") return hash === "#/" || hash.startsWith("#/clusters");
  return hash === href;
}

/** Three zones as in the reference header: wordmark, links, then theme toggle and sign out. */
export function AppHeader({ hash, username, onSignOut }: { hash: string; username: string; onSignOut: () => void }) {
  const { mode, toggle } = useThemeMode();
  const compact = useIsWithinBreakpoints(["xs", "s"]);
  const next = mode === "dark" ? "light" : "dark";
  return (
    <EuiHeader position="static" className="ecm-header" theme="default">
      <EuiHeaderSection grow className="ecm-header__left">
        <EuiHeaderSectionItem>
          <a className="ecm-wordmark" href="#/" title="Elasticsearch Cluster Manager">ECM</a>
        </EuiHeaderSectionItem>
      </EuiHeaderSection>
      <EuiHeaderSection grow={false}>
        <EuiHeaderLinks aria-label="Primary" gutterSize="xs"
          popoverBreakpoints={["xs", "s"]} popoverButtonProps={{ "aria-label": "Open navigation menu" }}>
          {NAV.map((n) => {
            const active = isActive(n.href, hash);
            return (
              <EuiHeaderLink key={n.href} href={n.href} isActive={active} className="ecm-nav-link"
                aria-current={active ? "page" : undefined}>{n.label}</EuiHeaderLink>);
          })}
        </EuiHeaderLinks>
      </EuiHeaderSection>
      <EuiHeaderSection grow className="ecm-header__right">
        <EuiHeaderSectionItem>
          <EuiButtonIcon iconType={mode === "dark" ? "sun" : "moon"} aria-label={`Switch to ${next} theme`}
            color="text" onClick={toggle} />
        </EuiHeaderSectionItem>
        <EuiHeaderSectionItem>
          {compact
            ? <EuiButtonIcon iconType="logOut" aria-label={`Sign out (${username})`} color="text" onClick={onSignOut} />
            : <EuiButtonEmpty iconType="logOut" color="text" onClick={onSignOut} title={`Signed in as ${username}`}>
              Sign out</EuiButtonEmpty>}
        </EuiHeaderSectionItem>
      </EuiHeaderSection>
    </EuiHeader>
  );
}
