import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    rules: {
      /**
       * Downgraded to a warning, not switched off.
       *
       * Atlas is a client-rendered app over a separate cookie-authenticated API, so pages
       * load their data in a mount effect and set state when the response arrives. The rule's
       * analysis does not cross the `await`, so it reports every one of those as a synchronous
       * cascading render. The same happens for reading `localStorage` on mount, which cannot
       * move into a lazy initialiser without breaking server rendering.
       *
       * Kept visible as a warning because the underlying advice is right when it applies —
       * state derived from props or from other state does not belong in an effect.
       */
      "react-hooks/set-state-in-effect": "warn",
    },
  },
]);

export default eslintConfig;
