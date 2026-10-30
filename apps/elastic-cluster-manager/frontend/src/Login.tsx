import { FormEvent, useState } from "react";
import { api, User } from "./api";

export function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      onLogin(await api<User>("/api/auth/login", {
        method: "POST", body: JSON.stringify({ username, password }),
      }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto mt-24 max-w-sm space-y-4 rounded-lg border p-6">
      <h1 className="text-xl font-semibold">Elastic Cluster Manager</h1>
      <label className="block text-sm">Username
        <input className="mt-1 w-full rounded border p-2" value={username}
          onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
      </label>
      <label className="block text-sm">Password
        <input type="password" className="mt-1 w-full rounded border p-2" value={password}
          onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      </label>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <button className="w-full rounded bg-slate-900 p-2 text-white">Sign in</button>
    </form>
  );
}
