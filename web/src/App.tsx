import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type User } from "./lib/api";
import { useMeta } from "./lib/meta";
import { Shell } from "./components/Shell";
import { PageError, PageLoading } from "./components/ui";
import { Today } from "./pages/Today";
import { Alerts } from "./pages/Alerts";
import { Pipeline } from "./pages/Pipeline";
import { Review } from "./pages/Review";
import { Insights } from "./pages/Insights";
import { Messages } from "./pages/Messages";
import { Settings } from "./pages/Settings";
import { Login } from "./pages/Login";
import { Consent } from "./pages/Consent";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/oauth/consent" element={<Authed><Consent /></Authed>} />
      <Route element={<Authed><Shell /></Authed>}>
        <Route index element={<Today />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="review" element={<Review />} />
        <Route path="messages" element={<Messages />} />
        <Route path="insights" element={<Insights />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

function Authed({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading, error, refetch } = useQuery({ queryKey: ["me"], queryFn: () => api.get<User>("/auth/me"), retry: false });
  const { data: meta } = useMeta();
  const qc = useQueryClient();

  // First run only: adopt the browser's timezone so "today" means the owner's today. Once a zone is
  // stored (even a deliberate UTC) it is never overwritten from here.
  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (meta && !meta.timezone_set && tz) {
      api.patch("/settings", { timezone: tz }).then(() => qc.invalidateQueries());
    }
  }, [meta, qc]);

  if (error && !me) return <PageError error={error} onRetry={refetch} />; // a 401 has already redirected to /login
  if (isLoading || !me) return <PageLoading />;
  return <>{children}</>;
}
