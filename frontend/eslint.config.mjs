import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// Under Cache Components, reading the clock while a server component prerenders bakes in a build-time value
// ("Blocking Route ... unstable value new Date()"). Route files must read it after `await connection()`.
const clockReadMessage =
  "Reading the current time in a route prerenders a build-time value. Call `await connection()` first " +
  "(see the Next docs: functions/connection), or read the clock in a client effect/event handler.";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["app/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        { selector: "NewExpression[callee.name='Date'][arguments.length=0]", message: clockReadMessage },
        { selector: "CallExpression[callee.object.name='Date'][callee.property.name='now']", message: clockReadMessage },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
