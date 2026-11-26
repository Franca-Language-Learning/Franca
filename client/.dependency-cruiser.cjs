/**
 * Module boundaries for the client (story E01-003), checked by dependency-cruiser.
 * Run with  pnpm --filter @franca/client boundaries
 *
 * Features live in src/features/<name>/. Another feature may import a feature's index file only, the same rule
 * as the server's modules, which import each other's package root only.
 */
/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "no-circular",
      comment: "With circular imports, the order of loading matters and design problems are harder to see.",
      severity: "error",
      from: {},
      to: { circular: true },
    },
    {
      name: "feature-index-only",
      comment: "A feature may import another feature only through that feature's index file.",
      severity: "error",
      from: { path: "^src/features/([^/]+)/" },
      to: {
        path: "^src/features/[^/]+/",
        pathNot: ["^src/features/$1/", "^src/features/[^/]+/index\\.tsx?$"],
      },
    },
    {
      name: "no-test-code-in-app",
      comment: "App code does not import tests or test helpers.",
      severity: "error",
      from: { pathNot: "\\.test\\.tsx?$|^src/test-setup\\.ts$" },
      to: { path: "\\.test\\.tsx?$|^src/test-setup\\.ts$" },
    },
    {
      name: "no-dev-dependencies-in-app",
      comment: "App code does not import packages that are only installed for development.",
      severity: "error",
      from: { path: "^src/", pathNot: "\\.test\\.tsx?$|^src/test-setup\\.ts$" },
      to: { dependencyTypes: ["npm-dev"] },
    },
    {
      name: "no-unresolvable",
      comment: "Every import resolves to a file or an installed package.",
      severity: "error",
      from: {},
      to: { couldNotResolve: true },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    exclude: { path: "^architecture-fixtures/" },
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.json" },
    enhancedResolveOptions: { exportsFields: ["exports"], conditionNames: ["import", "require", "node", "default"] },
  },
};
