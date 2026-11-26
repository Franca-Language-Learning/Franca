# Client

- React 19, Vite 8, TypeScript 6 (dependency-cruiser does not work with TypeScript 7.0. Move to 7.1 when it is released.). Run from the repository root: `pnpm --filter @franca/client test`, `typecheck`, `boundaries`, `build`.
- Features go in `src/features/<name>/`. A feature may import another feature only through that feature's `index.ts` or `index.tsx`. `pnpm --filter @franca/client boundaries` checks this.
- Accessibility: every component has a test with an axe check, and interactive components are built with React Aria Components (not installed yet; add it with the first interactive component).
- Interface text follows the writing rules in the language-standard skill and is reviewed by an independent agent.
