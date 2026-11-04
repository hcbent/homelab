import { EuiButton, EuiCallOut, EuiFieldPassword, EuiFieldText, EuiFormRow, EuiHealth } from "@elastic/eui";
import { CSSProperties, FormEvent, useState } from "react";
import { api, ApiError, User } from "./api";

const HEALTH_KEY = [
  { color: "success", name: "Green", text: "All shards are assigned." },
  { color: "warning", name: "Yellow", text: "Primaries are assigned, but a replica is not." },
  { color: "danger", name: "Red", text: "A primary shard is unassigned." },
  { color: "subdued", name: "Unknown", text: "No recent data from the cluster." },
];

export function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      onLogin(await api<User>("/api/auth/login", {
        method: "POST", body: JSON.stringify({ username, password }),
      }));
    } catch (err) {
      // Keep the username, never the password.
      setPassword("");
      setError(err instanceof ApiError && err.status === 401
        ? "Sign-in failed. Check the username and password, then try again."
        : (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const step = (i: number) => ({ "--i": i }) as CSSProperties;

  return (
    <main className="ecm-signin">
      <form onSubmit={submit} className="ecm-signin__form" aria-labelledby="signin-title">
        <h1 id="signin-title" className="ecm-display ecm-enter" style={step(0)}>
          Sign in to manage your Elasticsearch clusters.
        </h1>
        <p className="ecm-lede ecm-enter" style={step(1)}>Enter your ECM username and password.</p>
        {error && (
          <EuiCallOut role="alert" color="danger" size="s" title={error} className="ecm-enter" style={step(1)} />
        )}
        <div className="ecm-enter ecm-signin__fields" style={step(2)}>
          <EuiFormRow label="Username" fullWidth>
            <EuiFieldText fullWidth value={username} onChange={(e) => setUsername(e.target.value)}
              autoComplete="username" name="username" />
          </EuiFormRow>
          <EuiFormRow label="Password" fullWidth>
            <EuiFieldPassword fullWidth value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password" name="password" />
          </EuiFormRow>
        </div>
        <div className="ecm-enter" style={step(3)}>
          <EuiButton type="submit" fill isLoading={busy} className="ecm-signin__submit">Sign in</EuiButton>
        </div>
      </form>

      <section className="ecm-notch ecm-enter ecm-enter--panel" style={step(5)} aria-labelledby="health-key-title">
        <span className="ecm-notch__shape" aria-hidden="true">
          <span className="ecm-notch__a" />
          <span className="ecm-notch__b" />
        </span>
        <div className="ecm-notch__content">
          <h2 id="health-key-title" className="ecm-notch__title">How ECM shows health</h2>
          <ul className="ecm-health-key">
            {HEALTH_KEY.map((h) => (
              <li key={h.name}>
                <EuiHealth color={h.color}><strong>{h.name}</strong></EuiHealth>
                <span>{h.text}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </main>
  );
}
