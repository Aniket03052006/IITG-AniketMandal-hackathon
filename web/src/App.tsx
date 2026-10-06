import { TodayPage } from "./pages/TodayPage";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { ApiError } from "./api/client";
import { Shell } from "./components/Shell";
import { EmptyState } from "./components/ui";
import { AnalyzePage } from "./pages/AnalyzePage";
import { EventPage } from "./pages/EventPage";
import { EvidencePage } from "./pages/EvidencePage";
import { FeedPage } from "./pages/FeedPage";
import { StressPage } from "./pages/StressPage";
import { PortfolioEditorPage } from "./pages/PortfolioEditorPage";
import { PortfoliosPage } from "./pages/PortfoliosPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
});

function NotFound() {
  return (
    <EmptyState title="Page not found" action={<Link className="btn" to="/">Back to the Risk Feed</Link>}>
      That address does not exist in EventShock.
    </EmptyState>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<FeedPage />} />
            <Route path="today" element={<TodayPage />} />
            <Route path="analyze" element={<AnalyzePage />} />
            <Route path="events/:id" element={<EventPage />} />
            <Route path="pipeline" element={<Navigate to="/evidence?tab=pipeline" replace />} />
            <Route path="evidence" element={<EvidencePage />} />
            <Route path="stress" element={<StressPage />} />
            <Route path="portfolios" element={<PortfoliosPage />} />
            <Route path="portfolios/:id" element={<PortfolioEditorPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
