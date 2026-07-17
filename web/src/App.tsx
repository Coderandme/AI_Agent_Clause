/** Routes, and the gate in front of the one that costs money. */

import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { Layout } from "@/components/Layout";
import { Landing } from "@/pages/Landing";
import { Login } from "@/pages/Login";
import { Signup } from "@/pages/Signup";
import { Analyse } from "@/pages/Analyse";

/** Send anonymous visitors to the login page, remembering where they were going so they land back
 * there afterwards rather than being dumped on the home page. */
function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  // Wait for the /me check, or a reload flashes "logged out" before settling.
  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Landing />} />
          <Route path="login" element={<Login />} />
          <Route path="signup" element={<Signup />} />
          <Route
            path="analyse"
            element={
              <ProtectedRoute>
                <Analyse />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
