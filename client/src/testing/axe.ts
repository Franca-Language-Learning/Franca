// The accessibility check in the component tests. The page is not laid out or painted in jsdom, so colour contrast
// cannot be measured here. It is checked in the browser tests (e2e/).
import axe from "axe-core";
import { expect } from "vitest";

export async function expectNoAxeViolations(container: Element) {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(results.violations).toEqual([]);
}
