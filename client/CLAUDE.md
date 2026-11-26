# Client

- React 19, Vite 8, TypeScript 6 (dependency-cruiser does not work with TypeScript 7.0. Move to 7.1 when it is released.). Run from the repository root: `pnpm --filter @franca/client test`, `typecheck`, `boundaries`, `build`.
- Features go in `src/features/<name>/`. A feature may import another feature only through that feature's `index.ts` or `index.tsx`. `pnpm --filter @franca/client boundaries` checks this.
- Shared components are typed with their entry in `contracts/ui/components.ts`. A change to those props is a change to the contract.
- Browser tests are in `e2e/` and run with `pnpm --filter @franca/client e2e` against the built client and the real server. Put a Chromium path in FRANCA_CHROMIUM if Playwright's own Chromium is not installed.
- Accessibility: every component has a test with an axe check, and interactive components are built with React Aria Components (not installed yet; add it with the first interactive component).
- Interface text follows the writing rules in the language-standard skill and is reviewed by an independent agent.
- The API types in `src/api/schema.d.ts` are generated from `contracts/openapi.yaml` by `scripts/update-contract` (or `pnpm --filter @franca/client generate:api`). The pipeline fails if they are out of date.
- Tests use a mock API made from the contract (`src/mocks/`). A request that no handler answers fails the test. To give a specific answer in a test, use `server.use(http.get(...))`.
