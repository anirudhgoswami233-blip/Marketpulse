import { ForexView } from "@/components/forex/ForexView";
import { PageHeader } from "@/components/ui/primitives";

export const metadata = { title: "Forex & metals" };

export default function ForexPage() {
  return (
    <div className="space-y-3">
      <PageHeader title="Forex &amp; metals">
        Major currencies, Indian rupee pairs, gold and silver. Open any pair for its chart and signals.
      </PageHeader>
      <ForexView />
    </div>
  );
}
