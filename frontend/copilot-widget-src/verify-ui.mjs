import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const baseUrl = process.env.TICKET_APP_URL || "http://127.0.0.1:8000";
const screenshotDir = fileURLToPath(new URL("../../docs/screenshots/", import.meta.url));
fs.mkdirSync(screenshotDir, { recursive: true });

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const consoleErrors = [];
const pageErrors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("dialog", (dialog) => dialog.accept());

let createdId = null;
try {
  await page.goto(`${baseUrl}/?tab=dashboard`, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForSelector("#ticket-tbody", { timeout: 30_000 });
  await page.waitForFunction(() => typeof window.getTicketFormSnapshot === "function", null, {
    timeout: 30_000,
  });
  await page.waitForTimeout(8000);

  const widgetMounted = await page.locator("#copilot-widget-root > *").count();
  const pageButtons = await page.locator("button").allTextContents();

  const created = await page.evaluate(async () => {
    const tokenResponse = await fetch("/api/v1/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sub: "ui-verifier", roles: ["admin"] }),
    });
    const token = (await tokenResponse.json()).access_token;
    const response = await fetch("/api/v1/tickets/submit", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        title: "UI CRUD verification",
        content: "The office laptop cannot connect to the network. Asset LAPTOP-UI-001.",
        priority: "normal",
        submitter: "ui-verifier",
      }),
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  });
  createdId = created.ticket_id;

  await page.click("#btn-refresh");
  await page.waitForFunction(
    () => document.querySelector("#ticket-tbody")?.textContent.includes("UI CRUD verification"),
    null,
    { timeout: 20_000 },
  );

  const row = page.locator(`tr[data-ticket-id="${createdId}"]`);
  await row.locator('button[data-action="edit"]').click();
  await page.waitForFunction(
    () => document.querySelector("#ticket-title")?.value === "UI CRUD verification",
  );
  await page.fill("#ticket-title", "UI CRUD verification updated");
  await page.click("#btn-submit");
  await page.waitForFunction(
    () => document.querySelector("#ticket-tbody")?.textContent.includes("UI CRUD verification updated"),
    null,
    { timeout: 20_000 },
  );

  await page.click('button[data-tab="submit"]');
  await page.fill("#ticket-title", "");
  await page.fill("#ticket-desc", "电脑蓝屏无法开机，资产编号 LAPTOP-UI-001，请尽快处理");
  await page.fill("#ticket-submitter", "ui-verifier");
  await page.click("#btn-draft-check");
  await page.waitForFunction(
    () => document.querySelector("#route-preview")?.textContent.includes("工单草稿预检查"),
    null,
    { timeout: 30_000 },
  );
  const draft = await page.evaluate(() => ({
    title: document.querySelector("#ticket-title")?.value,
    description: document.querySelector("#ticket-desc")?.value,
    preview: document.querySelector("#route-preview")?.textContent,
  }));

  await page.screenshot({
    path: path.join(screenshotDir, "copilot-dashboard-desktop.png"),
    fullPage: true,
  });

  await page.click('button[data-tab="dashboard"]');
  await page.waitForSelector(`tr[data-ticket-id="${createdId}"]`);
  const deleteButton = page.locator(
    `tr[data-ticket-id="${createdId}"] button[data-action="delete"]`,
  );
  await deleteButton.click();
  await page.waitForFunction(
    (id) => !document.querySelector(`tr[data-ticket-id="${id}"]`),
    createdId,
    { timeout: 20_000 },
  );
  createdId = null;

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(`${baseUrl}/?tab=dashboard`, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await mobile.waitForSelector("#ticket-tbody", { timeout: 30_000 });
  await mobile.waitForTimeout(5000);
  await mobile.screenshot({
    path: path.join(screenshotDir, "copilot-dashboard-mobile.png"),
    fullPage: true,
  });
  await mobile.close();

  const result = {
    widgetMounted,
    pageButtons: pageButtons.filter(Boolean).slice(0, 30),
    draft,
    consoleErrors,
    pageErrors,
  };
  console.log(JSON.stringify(result, null, 2));

  if (!widgetMounted) throw new Error("CopilotKit widget did not mount");
  if (!draft.title || !draft.preview.includes("工单草稿预检查")) {
    throw new Error("Draft pre-check did not fill the form");
  }
  if (pageErrors.length) throw new Error(`Page errors: ${pageErrors.join(" | ")}`);
} finally {
  if (createdId) {
    try {
      await page.evaluate(async (id) => {
        const token = await fetch("/api/v1/auth/token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sub: "ui-verifier", roles: ["admin"] }),
        }).then((r) => r.json());
        await fetch(`/api/v1/tickets/${id}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token.access_token}` },
        });
      }, createdId);
    } catch {}
  }
  await browser.close();
}
