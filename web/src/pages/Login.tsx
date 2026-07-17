/** Sign in. SPEC.md §9.2: "Minimal, professional, same register as the rest — not a consumer-app
 * splash."
 *
 * On success we return the user to wherever they were headed (usually the upload they attempted),
 * which the protected route stashed in location.state.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { AuthCard, ErrorNote, Field, SubmitButton } from "@/components/Form";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/analyse";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Sign in" subtitle="Access to run the agent on your own contract is invite-only.">
      <form onSubmit={onSubmit} className="space-y-3">
        {error && <ErrorNote>{error}</ErrorNote>}
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          required
        />
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          required
        />
        <SubmitButton busy={busy}>{busy ? "Signing in…" : "Sign in"}</SubmitButton>
      </form>

      <p className="mt-4 text-xs text-slate-500">
        Have an access code but no account?{" "}
        <Link to="/signup" className="text-accent-700 underline underline-offset-2">
          Sign up
        </Link>
        . No code? The{" "}
        <Link to="/" className="text-accent-700 underline underline-offset-2">
          sample contracts
        </Link>{" "}
        are free and need no account.
      </p>
    </AuthCard>
  );
}
