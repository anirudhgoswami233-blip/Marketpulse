import { Suspense } from "react";

import { AuthForm } from "@/components/auth/AuthForm";
import { Card, SkeletonBlock } from "@/components/ui/primitives";

export const metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-sm py-6">
      <h1 className="mb-3 text-lg font-semibold text-primary">Sign in</h1>
      <Card>
        {/* useSearchParams (for ?next=) needs a Suspense boundary under Cache Components. */}
        <Suspense fallback={<SkeletonBlock lines={5} label="Loading form" />}>
          <AuthForm mode="login" />
        </Suspense>
      </Card>
    </div>
  );
}
