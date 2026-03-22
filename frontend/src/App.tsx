import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/layout";
import { LoginPage } from "./pages/login-page";
import { DashboardPage } from "./pages/dashboard-page";
import { DebuggerPage } from "./pages/debugger-page";
import { DocsPage } from "./pages/docs-page";
import { HistoryPage } from "./pages/history-page";
import { JobsPage } from "./pages/jobs-page";
import { RecommendationDetailPage } from "./pages/recommendation-detail-page";
import { RunDetailPage } from "./pages/run-detail-page";
import { SentimentSnapshotDetailPage } from "./pages/sentiment-snapshot-detail-page";
import { SentimentSnapshotsPage } from "./pages/sentiment-snapshots-page";
import { SettingsPage } from "./pages/settings-page";
import { TickerPage } from "./pages/ticker-page";
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
          <Route path="jobs/history" element={<HistoryPage />} />
          <Route path="jobs/debugger" element={<DebuggerPage />} />
          <Route path="watchlists" element={<Navigate to="/jobs/watchlists" replace />} />
          <Route path="history" element={<Navigate to="/jobs/history" replace />} />
          <Route path="debugger" element={<Navigate to="/jobs/debugger" replace />} />
          <Route path="sentiment" element={<SentimentSnapshotsPage />} />
          <Route path="sentiment/:snapshotId" element={<SentimentSnapshotDetailPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="runs/:runId" element={<RunDetailPage />} />
          <Route path="recommendations/:recommendationId" element={<RecommendationDetailPage />} />
          <Route path="tickers/:ticker" element={<TickerPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
