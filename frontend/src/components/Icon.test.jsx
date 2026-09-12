/**
 * The icons replaced emoji, and that changed two things a test should hold.
 *
 * Screen readers announce an emoji by its Unicode name, so "⚠️ Alerts" was read
 * as "warning sign, Alerts" — the glyph added noise, never information, because
 * the heading beside it already said the word. Icons are therefore decorative
 * by default and must stay that way.
 *
 * And the glyphs are ours now rather than the operating system's, which is the
 * point: the committed captures in docs/img/ and the walkthrough video render
 * the same everywhere.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AlertsPanel from "./AlertsPanel.jsx";
import Icon from "./Icon.jsx";
import ThemeToggle from "./ThemeToggle.jsx";

const svg = (c) => c.querySelector("svg");

describe("Icon", () => {
  it("is decorative by default, so nothing is announced twice", () => {
    const { container } = render(<Icon name="warning" />);
    expect(svg(container)).toHaveAttribute("aria-hidden", "true");
    expect(svg(container)).not.toHaveAttribute("role");
  });

  it("becomes an image with a name when it is the only thing carrying meaning", () => {
    render(<Icon name="lock" title="Read-only" />);
    const el = screen.getByRole("img", { name: "Read-only" });
    expect(el).not.toHaveAttribute("aria-hidden");
  });

  it("draws in currentColor, which is what makes one set work in both themes", () => {
    const { container } = render(<Icon name="sun" />);
    expect(svg(container)).toHaveAttribute("stroke", "currentColor");
    expect(svg(container)).toHaveAttribute("fill", "none");
  });

  it("renders nothing for a name it does not have, rather than an empty box", () => {
    const { container } = render(<Icon name="not-an-icon" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is not focusable — Safari and IE put SVGs in the tab order", () => {
    const { container } = render(<Icon name="brush" />);
    expect(svg(container)).toHaveAttribute("focusable", "false");
  });
});

describe("icons in place of emoji", () => {
  it("leaves the alerts heading reading as its words alone", () => {
    render(<AlertsPanel alerts={[{ id: "a", severity: "critical", title: "t", detail: "d" }]} />);

    const heading = screen.getByRole("heading", { name: /alerts/i });
    expect(heading).toHaveTextContent(/^\s*Alerts \(1\)\s*$/);
    expect(heading.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps the theme toggle's name on the button, where the icon is the label", () => {
    render(<ThemeToggle />);

    // The button has no text, so this name is the only thing a screen reader
    // has. An emoji used to supply a fallback; an aria-hidden path supplies none.
    const button = screen.getByRole("button", { name: /switch to (light|dark) theme/i });
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
