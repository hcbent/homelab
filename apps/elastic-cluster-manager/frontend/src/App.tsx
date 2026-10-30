import { useEffect, useState } from "react";
import { api, User } from "./api";
import { Login } from "./Login";
import { Operations } from "./Operations";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    api<User>("/api/auth/me").then(setUser).catch(() => {}).finally(() => setChecked(true));
  }, []);

  if (!checked) return null;
  if (!user) return <Login onLogin={setUser} />;

  return (
    <div className="mx-auto max-w-5xl p-4">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Elastic Cluster Manager</h1>
        <button className="text-sm underline" onClick={async () => {
          await api("/api/auth/logout", { method: "POST" });
          setUser(null);
        }}>Sign out ({user.username})</button>
      </header>
      <p className="mb-6 rounded bg-slate-100 p-3 text-sm">
        Cluster dashboard arrives in phase 3. Only the operations interface works today.
      </p>
      <Operations />
    </div>
  );
}
