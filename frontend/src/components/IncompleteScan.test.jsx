/**
 * The whole point of this panel is that silence means "we read everything".
 * If it ever renders nothing for a non-empty list, or something for an empty
 * one, the dashboard goes back to presenting a partial inventory as a complete
 * one — the failure mode this component exists to prevent.
 *
 * Two kinds of gap reach it. A region the sweep could not read, and a scanner
 * that could not run at all — S3 is global, so `list_buckets` failing names no
 * region and needs its own signal.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import IncompleteScan from "./IncompleteScan.jsx";

const region = (over = {}) => ({
  region: "us-west-1",
  reason: "AuthFailure",
  account_id: null,
  account_label: null,
  ...over,
});

const scanner = (over = {}) => ({
  scanner: "s3",
  label: "S3 buckets",
  reason: "AccessDenied",
  account_id: null,
  account_label: null,
  ...over,
});

describe("IncompleteScan", () => {
  it("renders nothing when the scan read everything", () => {
    const { container } = render(<IncompleteScan regions={[]} scanners={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the fields are absent", () => {
    // A saved scan carries neither field at all.
    const { container } = render(<IncompleteScan />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the region and why it could not be read", () => {
    render(<IncompleteScan regions={[region()]} />);

    expect(screen.getByText("us-west-1")).toBeInTheDocument();
    expect(screen.getByText("AuthFailure")).toBeInTheDocument();
  });

  it("says the results are incomplete rather than clean", () => {
    render(<IncompleteScan regions={[region()]} />);

    expect(screen.getByRole("status")).toHaveTextContent(/1 region could not be fully read/i);
    expect(screen.getByRole("status")).toHaveTextContent(/incomplete, not clean/i);
  });

  it("pluralizes and lists every failed region", () => {
    render(
      <IncompleteScan
        regions={[region(), region({ region: "ap-east-1", reason: "OptInRequired" })]}
      />
    );

    expect(screen.getByRole("status")).toHaveTextContent(/2 regions could not be fully read/i);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("attributes a failure to its account when scanning several", () => {
    render(
      <IncompleteScan
        regions={[region({ account_id: "111122223333", account_label: "sandbox-lab" })]}
      />
    );

    expect(screen.getByText("sandbox-lab")).toBeInTheDocument();
  });

  it("keeps the same region in two accounts distinct", () => {
    render(
      <IncompleteScan
        regions={[
          region({ account_id: "111122223333", account_label: "sandbox-lab" }),
          region({ account_id: "444455556666", account_label: "training-account" }),
        ]}
      />
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("sandbox-lab")).toBeInTheDocument();
    expect(screen.getByText("training-account")).toBeInTheDocument();
  });

  it("names an unavailable service without blaming a region", () => {
    // The service label, not the "s3" registry key, and no invented region.
    render(<IncompleteScan scanners={[scanner()]} />);

    expect(screen.getByRole("status")).toHaveTextContent(/1 service could not be fully read/i);
    expect(screen.getByText("S3 buckets")).toBeInTheDocument();
    expect(screen.getByText("AccessDenied")).toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent(/region/i);
  });

  it("keeps the same service in two accounts distinct", () => {
    render(
      <IncompleteScan
        scanners={[
          scanner({ account_id: "111122223333", account_label: "sandbox-lab" }),
          scanner({ account_id: "444455556666", account_label: "training-account" }),
        ]}
      />
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("reports both kinds of gap in one panel", () => {
    render(<IncompleteScan regions={[region()]} scanners={[scanner()]} />);

    // One panel, one verdict — not two stacked warnings saying it twice.
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent(
      /1 service and 1 region could not be fully read/i
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
});
