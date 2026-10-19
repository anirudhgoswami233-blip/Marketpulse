import { RequireAuth } from "@/components/auth/RequireAuth";
import { WatchlistsView } from "@/components/portfolio/WatchlistsView";

export const metadata = { title: "Watchlists" };

export default function WatchlistsPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-primary">Watchlists</h1>
      <RequireAuth what="watchlists">
        <WatchlistsView />
      </RequireAuth>
    </div>
  );
}
