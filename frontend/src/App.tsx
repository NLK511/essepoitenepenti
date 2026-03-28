import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/layout";
import { LoginPage } from "./pages/login-page";
import { DashboardPage } from "./pages/dashboard-page";
import { DebuggerPage } from "./pages/debugger-page";
import { DocsPage } from "./pages/docs-page";
import { ContextSnapshotDetailPage } from "./pages/context-snapshot-detail-page";
import { JobsPage } from "./pages/jobs-page";
import { RecommendationPlansPage } from "./pages/recommendation-plans-page";
import { RunDetailPage } from "./pages/run-detail-page";
import { SupportSnapshotDetailPage } from "./pages/sentiment-snapshot-detail-page";
import { ContextReviewPage } from "./pages/sentiment-snapshots-page";
import { SettingsPage } from "./pages/settings-page";
import { TickerPage } from "./pages/ticker-page";
import { TickerSignalsPage } from "./pages/ticker-signals-page";
import { WatchlistsPage } from "./pages/watchlists-page";
import { RequireAuth } from "./auth";

function NotFoundPage() {
  return <Navigate to="/" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<RequireAuth><AppLayout /></RequireAuth>}>
          <Route index element={<DashboardPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="jobs/watchlists" element={<WatchlistsPage />} />
          <Route path="jobs/history" element={<Navigate to="/jobs/recommendation-plans" replace />} />
          <Route path="jobs/ticker-signals" element={<TickerSignalsPage />} />
          <Route path="jobs/recommendation-plans" element={<RecommendationPlansPage />} />
          <Route path="jobs/debugger" element={<DebuggerPage />} />
          <Route path="watchlists" element={<Navigate to="/jobs/watchlists" replace />} />
          <Route path="history" element={<Navigate to="/jobs/recommendation-plans" replace />} />
          <Route path="ticker-signals" element={<Navigate to="/jobs/ticker-signals" replace />} />
          <Route path="recommendation-plans" element={<Navigate to="/jobs/recommendation-plans" replace />} />
          <Route path="debugger" element={<Navigate to="/jobs/debugger" replace />} />
          <Route path="context" element={<ContextReviewPage />} />
          <Route path="context/sentiment/:snapshotId" element={<SupportSnapshotDetailPage />} />
          <Route path="context/:scope/:snapshotId" element={<ContextSnapshotDetailPage />} />
          <Route path="sentiment" element={<Navigate to="/context" replace />} />
          <Route path="sentiment/:snapshotId" element={<SupportSnapshotDetailPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="runs/:runId" element={<RunDetailPage />} />
          <Route path="recommendations/:recommendationId" element={<Navigate to="/jobs/recommendation-plans" replace />} />
          <Route path="tickers/:ticker" element={<TickerPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
