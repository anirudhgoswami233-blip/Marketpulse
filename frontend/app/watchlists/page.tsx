import { RequireAuth } from "@/components/auth/RequireAuth";
import { WatchlistsView } from "@/components/portfolio/WatchlistsView";
import { PageHeader } from "@/components/ui/primitives";

export const metadata = { title: "Watchlists" };

export default function WatchlistsPage() {
  return (
    <div className="space-y-3">
      <PageHeader title="Watchlists" />
      <RequireAuth what="watchlists">
        <WatchlistsView />
      </RequireAuth>
    </div>
  );
}
