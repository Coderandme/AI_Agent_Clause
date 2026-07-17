/** Sign up — with an access code. SPEC.md §2.5, §9.2.
 *
 * The code field is required and validated server-side. This is the ONLY way an account that can
 * spend API budget comes into existence: no code, no account. That is the whole spend control, so
 * the page says so plainly rather than treating the code as an optional promo box.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { AuthCard, ErrorNote, Field, SubmitButton } from "@/components/Form";

export function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signup(email, password, code.trim());
      navigate("/analyse", { replace: true }); // signup logs you straight in
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign up failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Sign up"
      subtitle="You need an access code. Running the agent costs real money, so it is invite-only."
    >
      <form onSubmit={onSubmit} className="space-y-3">
        {error && <ErrorNote>{error}</ErrorNote>}
        <Field
          label="Access code"
          type="text"
          value={code}
          onChange={setCode}
          placeholder="CLAUSE-XXXX-XXXX"
          required
          hint="Single-use. If you don't have one, the sample contracts are free and need no account."
        />
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
          autoComplete="new-password"
          required
          hint="At least 8 characters."
        />
        <SubmitButton busy={busy}>{busy ? "Creating account…" : "Create account"}</SubmitButton>
      </form>

      <p className="mt-4 text-xs text-slate-500">
        Already have an account?{" "}
        <Link to="/login" className="text-accent-700 underline underline-offset-2">
          Sign in
        </Link>
        .
      </p>
    </AuthCard>
  );
}
