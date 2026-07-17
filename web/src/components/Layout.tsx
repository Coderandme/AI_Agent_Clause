/** The page shell: header, nav, and the disclaimer that SPEC.md §2.4 calls non-negotiable.
 *
 * "Persistent, unmissable, on every page... Present before the first analysis renders, not buried in
 * a footer link." So it lives in the shell, above the content, on every route.
 */

import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";

export const DISCLAIMER =
  "Clause is an automated analysis tool. It is not a lawyer and does not provide legal advice. " +
  "Its output is a starting point for review by qualified counsel, not a substitute for it.";

export function Disclaimer() {
  return (
    <p className="border-y border-amber-200 bg-amber-50 px-4 py-2 text-center text-[12px] text-amber-900">
      <strong className="font-semibold">Not legal advice.</strong> {DISCLAIMER}
    </p>
  );
}

export function Layout() {
  const { user, logout } = useAuth();

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `text-sm ${isActive ? "font-semibold text-slate-900" : "text-slate-500 hover:text-slate-800"}`;

  return (
    <div className="min-h-dvh">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <Link to="/" className="flex items-baseline gap-2">
            <span className="text-lg font-semibold tracking-tight text-slate-900">Clause</span>
            <span className="hidden text-xs text-slate-400 sm:inline">contract intelligence</span>
          </Link>

          <nav className="flex items-center gap-4">
            <NavLink to="/" className={linkClass} end>
              Samples
            </NavLink>
            <NavLink to="/analyse" className={linkClass}>
              Analyse
            </NavLink>
            {user ? (
              <div className="flex items-center gap-3 border-l border-slate-200 pl-4">
                <span className="hidden text-xs text-slate-500 sm:inline">
                  {user.email}
                  {user.is_admin && (
                    <span className="ml-1.5 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                      ADMIN
                    </span>
                  )}
                </span>
                {/* Same blue as Sign in: they occupy the same slot in the header and swap based on
                    whether you're logged in, so they should read as the same control. */}
                <button
                  onClick={logout}
                  className="rounded bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700"
                  type="button"
                >
                  Sign out
                </button>
              </div>
            ) : (
              <Link
                to="/login"
                className="rounded bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700"
              >
                Sign in
              </Link>
            )}
          </nav>
        </div>
      </header>

      <Disclaimer />

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-6xl px-4 py-8 text-xs text-slate-400">
        Sample contracts are pre-computed and cost nothing to view. Uploading your own contract is
        invite-only.
      </footer>
    </div>
  );
}
