import { RequireAuth } from "@/components/auth/RequireAuth";
import { PortfolioView } from "@/components/portfolio/PortfolioView";

export const metadata = { title: "Paper portfolio" };

export default function PortfolioPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-primary">Paper portfolio</h1>
      <RequireAuth what="paper portfolio">
        <PortfolioView />
      </RequireAuth>
    </div>
  );
}
