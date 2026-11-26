# Client

- React 19, Vite 8, TypeScript 6 (TypeScript 7.0 cannot be read by dependency-cruiser; move to 7.1 when it is released). Run from the repository root: `pnpm --filter @franca/client test`, `typecheck`, `boundaries`, `build`.
- Features go in `src/features/<name>/`. Another feature imports a feature through its `index.ts` only; `pnpm --filter @franca/client boundaries` checks this.
- Accessibility: every component has a test with an axe check, and interactive components use React Aria Components.
- Interface text follows the writing rules in the language-standard skill and is reviewed by an independent agent.
