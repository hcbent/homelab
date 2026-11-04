import { EuiLoadingSpinner, EuiPageTemplate, EuiSkipLink } from "@elastic/eui";
import { useEffect, useState } from "react";
import { AppHeader } from "./AppHeader";
import { api, User } from "./api";
import { ClusterDetailView } from "./ClusterDetailView";
import { Dashboard } from "./Dashboard";
import { Help } from "./Help";
import { InfrastructureView } from "./InfrastructureView";
import { Login } from "./Login";
import { Operations } from "./Operations";
import { ThemeProvider } from "./theme";

function useHash() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function Shell() {
  const [user, setUser] = useState<User | null>(null);
  const [checked, setChecked] = useState(false);
  const hash = useHash();

  useEffect(() => {
    api<User>("/api/auth/me").then(setUser).catch(() => {}).finally(() => setChecked(true));
  }, []);

  if (!checked) return <div className="ecm-boot" role="status" aria-label="Loading"><EuiLoadingSpinner size="xl" /></div>;
  if (!user) return <Login onLogin={setUser} />;

  const cluster = hash.match(/^#\/clusters\/([\w-]+)/);

  return (
    <>
      <EuiSkipLink destinationId="main">Skip to content</EuiSkipLink>
      <div className="ecm-sticky">
        <AppHeader hash={hash} username={user.username} onSignOut={async () => {
          await api("/api/auth/logout", { method: "POST" });
          setUser(null);
        }} />
      </div>
      <EuiPageTemplate restrictWidth={1440} offset={0} minHeight="calc(100vh - 48px)" paddingSize="l"
        panelled={false} grow={false} mainProps={{ id: "main" }}>
        <EuiPageTemplate.Section color="transparent" className="ecm-page">
          {cluster ? <ClusterDetailView key={cluster[1]} id={cluster[1]} />
            : hash === "#/infrastructure" ? <InfrastructureView />
            : hash === "#/operations" ? <Operations />
            : hash === "#/help" ? <Help />
            : <Dashboard />}
        </EuiPageTemplate.Section>
      </EuiPageTemplate>
    </>
  );
}

export default function App() {
  return <ThemeProvider><Shell /></ThemeProvider>;
}
