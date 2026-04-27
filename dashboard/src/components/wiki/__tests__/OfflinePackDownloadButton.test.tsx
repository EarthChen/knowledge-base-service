import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { TestI18nProvider } from "../../../i18n/context";
import en from "../../../i18n/en";
import zh from "../../../i18n/zh";
import { OfflinePackDownloadButton } from "../OfflinePackDownloadButton";

describe("OfflinePackDownloadButton", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ pages: [] }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders download button (English i18n)", () => {
    render(
      <TestI18nProvider locale="en">
        <OfflinePackDownloadButton repository="test-repo" businessId="b1" />
      </TestI18nProvider>,
    );
    expect(screen.getByRole("button", { name: en.wiki.offlinePackButton })).toBeInTheDocument();
  });

  it("renders download button in Chinese", () => {
    render(
      <TestI18nProvider locale="zh">
        <OfflinePackDownloadButton repository="test-repo" businessId="b1" />
      </TestI18nProvider>,
    );
    expect(screen.getByRole("button", { name: zh.wiki.offlinePackButton })).toBeInTheDocument();
  });

  it("shows Chinese downloading label while loading", async () => {
    globalThis.fetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          setTimeout(
            () =>
              resolve(
                new Response(JSON.stringify({ pages: [] }), {
                  status: 200,
                  headers: { "Content-Type": "application/json" },
                }),
              ),
            100,
          );
        }),
    );
    render(
      <TestI18nProvider locale="zh">
        <OfflinePackDownloadButton repository="test-repo" businessId="b1" />
      </TestI18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: zh.wiki.offlinePackButton }));
    expect(await screen.findByRole("button", { name: zh.wiki.offlinePackDownloading })).toBeInTheDocument();
  });

  it("shows Chinese truncation notice when API marks truncated", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ pages: [], truncated: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(
      <TestI18nProvider locale="zh">
        <OfflinePackDownloadButton repository="test-repo" businessId="b1" />
      </TestI18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: zh.wiki.offlinePackButton }));
    await waitFor(() => {
      expect(screen.getByText(zh.wiki.offlinePackDataTruncated, { exact: true })).toBeInTheDocument();
    });
  });
});
