import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library does not auto-clean under vitest's globals-off setup.
afterEach(cleanup);

// jsdom implements neither, and both are load-bearing here: ThemeToggle reads
// `matchMedia` to follow the OS theme, and Dashboard calls `scrollIntoView`
// when a scan finishes. Stubbed once rather than in every file that renders
// them.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  });
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
