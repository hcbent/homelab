import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import App from "./App";

afterEach(() => vi.restoreAllMocks());

function mockFetch(handler: (url: string, init?: RequestInit) => [number, unknown]) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const [status, body] = handler(url, init);
    return new Response(JSON.stringify(body), { status });
  }));
}

test("unauthenticated users see the login form", async () => {
  mockFetch(() => [401, { detail: "Not authenticated" }]);
  render(<App />);
  expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
});

test("failed login shows an error", async () => {
  mockFetch((url) => url.endsWith("/login") ? [401, { detail: "Invalid credentials" }]
    : [401, { detail: "x" }]);
  render(<App />);
  await userEvent.type(await screen.findByLabelText(/username/i), "admin");
  await userEvent.type(screen.getByLabelText(/password/i), "nope");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
});

test("authenticated users see operations", async () => {
  mockFetch((url) => url.endsWith("/me") ? [200, { username: "admin", role: "admin" }] : [200, []]);
  render(<App />);
  await waitFor(() => expect(screen.getByText(/Operations/)).toBeInTheDocument());
});
