/**
 * The whole point of this panel is that silence means "we read everything".
 * If it ever renders nothing for a non-empty list, or something for an empty
 * one, the dashboard goes back to presenting a partial inventory as a complete
 * one — the failure mode this component exists to prevent.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RegionFailures from "./RegionFailures.jsx";

const failure = (over = {}) => ({
  region: "us-west-1",
  reason: "AuthFailure",
  account_id: null,
  account_label: null,
  ...over,
});

describe("RegionFailures", () => {
  it("renders nothing when every region was read", () => {
    const { container } = render(<RegionFailures failures={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the field is absent", () => {
    // A saved scan does not carry the field at all.
    const { container } = render(<RegionFailures failures={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the region and why it could not be read", () => {
    render(<RegionFailures failures={[failure()]} />);

    expect(screen.getByText("us-west-1")).toBeInTheDocument();
    expect(screen.getByText("AuthFailure")).toBeInTheDocument();
  });

  it("says the results are incomplete rather than clean", () => {
    render(<RegionFailures failures={[failure()]} />);

    expect(screen.getByRole("status")).toHaveTextContent(/1 region could not be fully read/i);
    expect(screen.getByRole("status")).toHaveTextContent(/incomplete, not clean/i);
  });

  it("pluralizes and lists every failed region", () => {
    render(
      <RegionFailures
        failures={[failure(), failure({ region: "ap-east-1", reason: "OptInRequired" })]}
      />
    );

    expect(screen.getByRole("status")).toHaveTextContent(/2 regions could not be fully read/i);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("attributes a failure to its account when scanning several", () => {
    render(
      <RegionFailures
        failures={[failure({ account_id: "111122223333", account_label: "sandbox-lab" })]}
      />
    );

    expect(screen.getByText("sandbox-lab")).toBeInTheDocument();
  });

  it("keeps the same region in two accounts distinct", () => {
    render(
      <RegionFailures
        failures={[
          failure({ account_id: "111122223333", account_label: "sandbox-lab" }),
          failure({ account_id: "444455556666", account_label: "training-account" }),
        ]}
      />
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("sandbox-lab")).toBeInTheDocument();
    expect(screen.getByText("training-account")).toBeInTheDocument();
  });
});
