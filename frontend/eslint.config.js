import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";

// Deliberately minimal (FIXLOG #380): the one class of bug we MUST catch at CI
// is a reference to an undefined variable — it white-screens the whole page and
// Vite's build does not catch it. `no-undef` alone does that. We are NOT
// adopting a full style ruleset here (that would flood the existing tree); add
// more rules later if wanted.
export default [
  {
    files: ["src/**/*.{js,jsx}"],
    // The inline exhaustive-deps disables are "unused" now that the rule is off;
    // don't warn on them (they document intent and stay valid if the rule is
    // ever turned on).
    linterOptions: { reportUnusedDisableDirectives: "off" },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      // Browser runtime + a few build/test globals so real globals aren't
      // mistaken for undefined references.
      globals: { ...globals.browser, ...globals.node },
    },
    // Registered ONLY so the many inline `// eslint-disable-next-line
    // react-hooks/exhaustive-deps` comments resolve to a known rule (an unknown
    // rule in a disable directive is itself an error). The rule stays OFF — we
    // are not adopting the hooks ruleset here, just the no-undef gate.
    plugins: { "react-hooks": reactHooks },
    rules: {
      "no-undef": "error",
      "react-hooks/exhaustive-deps": "off",
    },
  },
];
