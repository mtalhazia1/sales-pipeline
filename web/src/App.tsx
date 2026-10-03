import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type User } from "./lib/api";
import { useMeta } from "./lib/meta";
import { Shell } from "./components/Shell";
import { PageLoading } from "./components/ui";
import { Today } from "./pages/Today";
import { Pipeline } from "./pages/Pipeline";
import { Review } from "./pages/Review";
import { Insights } from "./pages/Insights";
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
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="review" element={<Review />} />
        <Route path="insights" element={<Insights />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

function Authed({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading } = useQuery({ queryKey: ["me"], queryFn: () => api.get<User>("/auth/me"), retry: false });
  const { data: meta } = useMeta();
  const qc = useQueryClient();

  // First run: adopt the browser's timezone so "today" means the owner's today.
  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (meta && meta.timezone === "UTC" && tz && tz !== "UTC") {
      api.patch("/settings", { timezone: tz }).then(() => qc.invalidateQueries());
    }
  }, [meta, qc]);

  if (isLoading || !me) return <PageLoading />;
  return <>{children}</>;
}
