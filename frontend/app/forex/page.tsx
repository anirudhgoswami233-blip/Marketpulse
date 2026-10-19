import { ForexView } from "@/components/forex/ForexView";

export const metadata = { title: "Forex & metals" };

export default function ForexPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-primary">Forex &amp; metals</h1>
        <p className="mt-1 text-sm text-secondary">
          Major currencies, Indian rupee pairs, gold and silver. Open any pair for its chart and signals.
        </p>
      </div>
      <ForexView />
    </div>
  );
}
