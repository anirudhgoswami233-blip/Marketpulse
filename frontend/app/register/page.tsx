import { Suspense } from "react";

import { AuthForm } from "@/components/auth/AuthForm";
import { Card, SkeletonBlock } from "@/components/ui/primitives";

export const metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <div className="mx-auto max-w-sm py-8">
      <h1 className="mb-1 text-2xl font-semibold text-primary">Create your account</h1>
      <p className="mb-4 text-sm text-secondary">
        Save watchlists and practise trading with $100,000 of virtual money. No real money is involved.
      </p>
      <Card>
        <Suspense fallback={<SkeletonBlock lines={6} label="Loading form" />}>
          <AuthForm mode="register" />
        </Suspense>
      </Card>
    </div>
  );
}
