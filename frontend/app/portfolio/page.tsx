import { RequireAuth } from "@/components/auth/RequireAuth";
import { PortfolioView } from "@/components/portfolio/PortfolioView";
import { PageHeader } from "@/components/ui/primitives";

export const metadata = { title: "Paper portfolio" };

export default function PortfolioPage() {
  return (
    <div className="space-y-3">
      <PageHeader title="Paper portfolio" />
      <RequireAuth what="paper portfolio">
        <PortfolioView />
      </RequireAuth>
    </div>
  );
}
