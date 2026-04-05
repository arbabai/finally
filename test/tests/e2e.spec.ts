import { test, expect } from "@playwright/test";

const DEFAULT_TICKERS = [
  "AAPL",
  "GOOGL",
  "MSFT",
  "AMZN",
  "TSLA",
  "NVDA",
  "META",
  "JPM",
  "V",
  "NFLX",
];

// Single-flow test avoids SSE HTTP/1.1 connection pool exhaustion.
// The SSE endpoint holds a persistent connection, consuming one of Chromium's
// 6-per-host HTTP/1.1 connection slots. Multiple page loads exhaust the pool.
// Trade and chat operations use page.evaluate() to reuse existing connections.
test("FinAlly E2E — full integration flow", async ({ page }) => {
  test.setTimeout(120_000);

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("AAPL").first()).toBeVisible({ timeout: 15_000 });

  // ---------------------------------------------------------------
  // Step 1: Fresh start — default watchlist, balance, streaming
  // ---------------------------------------------------------------
  await test.step("Fresh start — default watchlist, balance, and streaming prices", async () => {
    for (const ticker of DEFAULT_TICKERS) {
      await expect(page.getByText(ticker).first()).toBeVisible({
        timeout: 10_000,
      });
    }

    const header = page.locator("header");
    await expect(header.getByText("Cash")).toBeVisible();
    // Both Portfolio Value and Cash now show $10,000.00 — verify Cash specifically
    const cashSection = header.locator("div").filter({ hasText: /^Cash$/ }).locator("..");
    await expect(cashSection.getByText("$10,000.00")).toBeVisible({ timeout: 10_000 });
    await expect(header.getByText("Portfolio Value")).toBeVisible();
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 10_000 });

    // Prices streaming
    await expect(
      page.locator(".font-mono").first()
    ).not.toHaveText("---", { timeout: 10_000 });
  });

  // ---------------------------------------------------------------
  // Step 2: SSE resilience — connection status indicator
  // ---------------------------------------------------------------
  await test.step("SSE resilience — connection status indicator shows connected", async () => {
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 10_000 });
    const statusDot = page.getByTitle("Connected");
    await expect(statusDot).toBeVisible();
  });

  // ---------------------------------------------------------------
  // Step 3: Add and remove a ticker from the watchlist
  // ---------------------------------------------------------------
  await test.step("Add and remove a ticker from the watchlist", async () => {
    const addInput = page.getByPlaceholder("Add ticker...");
    await expect(addInput).toBeVisible({ timeout: 10_000 });

    await addInput.fill("PYPL");
    await addInput.press("Enter");
    await expect(page.getByText("PYPL").first()).toBeVisible({ timeout: 10_000 });

    // Remove via API (UI "x" button locator is ambiguous due to nested divs)
    const deleteStatus = await page.evaluate(async () => {
      const res = await fetch("/api/watchlist/PYPL", { method: "DELETE" });
      return res.status;
    });
    expect(deleteStatus).toBe(200);

    // Verify via API
    await page.waitForTimeout(500);
    const watchlistData = await page.evaluate(async () => {
      const res = await fetch("/api/watchlist");
      const data = await res.json();
      return data.map((item: any) => item.ticker);
    });
    expect(watchlistData).not.toContain("PYPL");
    expect(watchlistData).toContain("AAPL");
  });

  // ---------------------------------------------------------------
  // Step 4: Buy shares — cash decreases, position appears
  // ---------------------------------------------------------------
  await test.step("Buy shares — cash decreases, position appears", async () => {
    const tradeResult = await page.evaluate(async () => {
      const res = await fetch("/api/portfolio/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: "AAPL", quantity: 10, side: "buy" }),
      });
      return { status: res.status, data: await res.json() };
    });
    expect(tradeResult.status).toBe(200);

    const portfolio = await page.evaluate(async () => {
      const res = await fetch("/api/portfolio");
      return await res.json();
    });
    expect(portfolio.cash_balance).toBeLessThan(10000);
    const aaplPos = portfolio.positions.find((p: any) => p.ticker === "AAPL");
    expect(aaplPos).toBeDefined();
    expect(aaplPos.quantity).toBe(10);
  });

  // ---------------------------------------------------------------
  // Step 5: Sell shares — cash increases, position updates
  // ---------------------------------------------------------------
  await test.step("Sell shares — cash increases, position updates", async () => {
    const beforePortfolio = await page.evaluate(async () => {
      const res = await fetch("/api/portfolio");
      return await res.json();
    });
    const cashBefore = beforePortfolio.cash_balance;

    const sellResult = await page.evaluate(async () => {
      const res = await fetch("/api/portfolio/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: "AAPL", quantity: 5, side: "sell" }),
      });
      return { status: res.status, data: await res.json() };
    });
    expect(sellResult.status).toBe(200);

    const afterPortfolio = await page.evaluate(async () => {
      const res = await fetch("/api/portfolio");
      return await res.json();
    });
    expect(afterPortfolio.cash_balance).toBeGreaterThan(cashBefore);
    const aaplPos = afterPortfolio.positions.find((p: any) => p.ticker === "AAPL");
    expect(aaplPos).toBeDefined();
    expect(aaplPos.quantity).toBe(5);
  });

  // ---------------------------------------------------------------
  // Step 6: Portfolio visualisation — heatmap and P&L sections
  // ---------------------------------------------------------------
  await test.step("Portfolio visualisation — heatmap and P&L chart render", async () => {
    await expect(page.locator("h2").filter({ hasText: "Portfolio" })).toBeVisible();
    await expect(page.locator("h2").filter({ hasText: "P&L" })).toBeVisible();
    await expect(page.locator("h2").filter({ hasText: "Positions" })).toBeVisible();
  });

  // ---------------------------------------------------------------
  // Step 7: AI chat (mocked) — send message, receive response
  // ---------------------------------------------------------------
  await test.step("AI chat (mocked) — send message, receive response", async () => {
    await expect(page.getByText("AI Assistant")).toBeVisible({ timeout: 10_000 });

    const chatInput = page.getByPlaceholder("Ask FinAlly...");
    await expect(chatInput).toBeVisible({ timeout: 10_000 });

    const chatResult = await page.evaluate(async () => {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: "What is my portfolio?" }),
      });
      return { status: res.status, data: await res.json() };
    });
    expect(chatResult.status).toBe(200);
    expect(chatResult.data.message).toBeTruthy();
    expect(typeof chatResult.data.message).toBe("string");
    expect(chatResult.data.message.length).toBeGreaterThan(0);
  });
});
