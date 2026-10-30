import { useEffect, useState } from "react";
import { api, User } from "./api";
import { ClusterDetailView } from "./ClusterDetailView";
import { Dashboard } from "./Dashboard";
import { InfrastructureView } from "./InfrastructureView";
import { Login } from "./Login";
import { Operations } from "./Operations";

function useHash() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checked, setChecked] = useState(false);
  const hash = useHash();

  useEffect(() => {
    api<User>("/api/auth/me").then(setUser).catch(() => {}).finally(() => setChecked(true));
  }, []);

  if (!checked) return null;
  if (!user) return <Login onLogin={setUser} />;

  const cluster = hash.match(/^#\/clusters\/(\w+)/);
  const link = (href: string, label: string) => (
    <a href={href} className={hash === href ? "font-medium underline" : ""}>{label}</a>);

  return (
    <div className="mx-auto max-w-6xl p-4">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <h1 className="text-xl font-semibold">Elastic Cluster Manager</h1>
          <nav className="flex gap-4 text-sm">
            {link("#/", "Clusters")}{link("#/infrastructure", "Infrastructure")}{link("#/operations", "Operations")}
          </nav>
        </div>
        <button className="text-sm underline" onClick={async () => {
          await api("/api/auth/logout", { method: "POST" });
          setUser(null);
        }}>Sign out ({user.username})</button>
      </header>
      {cluster ? <ClusterDetailView id={cluster[1]} />
        : hash === "#/infrastructure" ? <InfrastructureView />
        : hash === "#/operations" ? <Operations />
        : <Dashboard />}
    </div>
  );
}
