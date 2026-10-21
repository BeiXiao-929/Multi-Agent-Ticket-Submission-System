import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const baseUrl = process.env.TICKET_APP_URL || "http://127.0.0.1:8000";
const screenshotDir = fileURLToPath(new URL("../../docs/screenshots/", import.meta.url));
fs.mkdirSync(screenshotDir, { recursive: true });

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const runtimeRequests = [];
const errors = [];

page.on("response", async (response) => {
  if (!response.url().includes("/api/v1/copilotkit/")) return;
  runtimeRequests.push({
    method: response.request().method(),
    url: response.url(),
    status: response.status(),
  });
});
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});

try {
  await page.goto(`${baseUrl}/?tab=dashboard`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  await page.waitForFunction(
    () => typeof window.getTicketFormSnapshot === "function",
    null,
    { timeout: 30_000 },
  );
  await page.getByTestId("copilot-chat-toggle").waitFor({ state: "visible", timeout: 30_000 });
  await page.getByTestId("copilot-chat-toggle").click();
  await page.getByTestId("copilot-chat-textarea").fill(
    "电脑蓝屏无法开机，资产编号 LAPTOP-CHAT-001，请尽快处理",
  );
  await page.getByTestId("copilot-send-button").click();

  await page.waitForFunction(
    () => {
      const title = document.querySelector("#ticket-title")?.value || "";
      const description = document.querySelector("#ticket-desc")?.value || "";
      return title.length > 0 && description.includes("LAPTOP-CHAT-001");
    },
    null,
    { timeout: 45_000 },
  );
  await page.waitForTimeout(500);

  const result = await page.evaluate(() => ({
    title: document.querySelector("#ticket-title")?.value || "",
    description: document.querySelector("#ticket-desc")?.value || "",
    chatText: document.querySelector('[data-testid="copilot-chat"]')?.textContent || "",
    submittedTicketCount: document.querySelectorAll("#ticket-tbody tr[data-ticket-id]").length,
  }));

  await page.screenshot({
    path: path.join(screenshotDir, "copilot-chat-desktop.png"),
    fullPage: true,
  });

  const runRequests = runtimeRequests.filter((request) => request.url.endsWith("/agent/ticket_assistant/run"));
  const output = { ...result, runtimeRequests, errors };
  console.log(JSON.stringify(output, null, 2));

  if (!runtimeRequests.some((request) => request.url.endsWith("/info") && request.status === 200)) {
    throw new Error("CopilotKit runtime info handshake failed");
  }
  if (!runRequests.some((request) => request.status === 200)) {
    throw new Error("LangGraph agent run did not complete successfully");
  }
  if (!result.title || !result.description.includes("LAPTOP-CHAT-001")) {
    throw new Error("fillTicketForm did not populate the visible form");
  }
  if (result.chatText.includes("已提交") || result.chatText.includes("Submitted")) {
  if (!result.chatText.includes("请核对自动生成内容后再提交")) {
    throw new Error("The localized review notice is missing");
  }
    throw new Error("The copilot claimed to submit a ticket without human approval");
  }
} finally {
  await browser.close();
}
