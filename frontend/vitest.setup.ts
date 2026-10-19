import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// findBy* waits up to 1s by default; the first test in a file also pays for module loading, which can
// exceed that on a busy machine. 3s avoids false failures without hiding real hangs.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
