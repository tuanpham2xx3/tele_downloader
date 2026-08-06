const fileInput = document.querySelector("#file");
const delayInput = document.querySelector("#delay");
const pageWaitInput = document.querySelector("#pageWait");
const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const saveLogButton = document.querySelector("#saveLog");
const completedElement = document.querySelector("#completed");
const totalElement = document.querySelector("#total");
const progressBar = document.querySelector("#progressBar");
const statusElement = document.querySelector("#status");
const logElement = document.querySelector("#log");

let queue = [];
let logEntries = [];
let stopRequested = false;
let activeAutomationTabId = null;

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function parseUrls(text) {
  const urls = text.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  return [...new Set(urls)].filter((value) => {
    try {
      const url = new URL(value);
      return url.protocol === "https:" && url.hostname === "www.cbusters.com";
    } catch {
      return false;
    }
  });
}

function setStatus(message) {
  statusElement.textContent = message;
}

function updateProgress(completed) {
  completedElement.textContent = String(completed);
  totalElement.textContent = String(queue.length);
  progressBar.style.width = queue.length ? `${(completed / queue.length) * 100}%` : "0%";
}

function appendLog(index, status, url, detail) {
  const entry = { index, status, url, detail };
  logEntries.push(entry);
  const row = document.createElement("tr");
  for (const [value, className] of [
    [index, ""],
    [status, status === "Thành công" ? "success" : "failed"],
    [url, ""],
    [detail, ""]
  ]) {
    const cell = document.createElement("td");
    cell.textContent = String(value);
    if (className) cell.className = className;
    row.appendChild(cell);
  }
  logElement.prepend(row);
  saveLogButton.disabled = false;
}

function waitForTabComplete(tabId, timeoutMs = 20000) {
  return new Promise(async (resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error("Trang tải quá thời gian."));
    }, timeoutMs);

    const listener = (updatedTabId, changeInfo, tab) => {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(tab);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);

    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(tab);
      }
    } catch (error) {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      reject(error);
    }
  });
}

function isTelegramLanding(url) {
  try {
    return new URL(url).hostname === "t.me";
  } catch {
    return false;
  }
}

function unwrapRedirectUrl(value) {
  try {
    const url = new URL(value);
    if (url.hostname === "www.google.com" && url.pathname === "/url") {
      const target = url.searchParams.get("q") || url.searchParams.get("url");
      if (target) return target;
    }
  } catch {
    // Keep the original URL when it cannot be parsed.
  }
  return value;
}

async function waitUntilInjectable(tabId, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        func: () => document.readyState
      });
      return;
    } catch {
      await sleep(250);
    }
  }
  throw new Error("Không thể truy cập trang Telegram trung gian.");
}

async function waitForUrlPrefix(tabId, prefix, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.url?.startsWith(prefix)) return tab;
    await sleep(250);
  }
  throw new Error(`Trang không chuyển tới ${prefix}`);
}

async function openTelegramWeb(tabId) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      const [{ result: clicked }] = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          const button = document.querySelector("a.tgme_action_web_button");
          if (!button) return false;
          button.scrollIntoView({ block: "center", inline: "center" });
          button.click();
          return true;
        }
      });

      if (clicked) {
        try {
          await waitForUrlPrefix(tabId, "https://web.telegram.org/", 5000);
          return tabId;
        } catch {
          // The page stayed on t.me; retry the same OPEN IN WEB button.
        }
      }
    } catch {
      // The t.me document may still be replacing its content; retry shortly.
    }
    await sleep(500);
  }
  throw new Error("Không bấm được nút OPEN IN WEB sau 20 giây.");
}

async function findPageAction(tabId, expectedText, timeoutMs = 10000) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: async (label, maximumWait) => {
      const normalize = (value) => (value || "").replace(/\s+/g, " ").trim().toLowerCase();
      const expected = normalize(label);
      const deadline = Date.now() + maximumWait;

      while (Date.now() < deadline) {
        const candidates = [...document.querySelectorAll("a, button, [role='button'], p")];
        const match = candidates.find((element) => normalize(element.textContent) === expected);
        if (match) {
          const actionable = match.closest("a, button, [role='button']") || match.parentElement;
          const href = actionable?.closest?.("a[href]")?.href || "";
          if (href) return { href };
          actionable?.click();
          return { clicked: true };
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
      return { error: `Không tìm thấy nút: ${label}` };
    },
    args: [expectedText, timeoutMs]
  });
  if (!result || result.error) throw new Error(result?.error || `Không tìm thấy ${expectedText}.`);
  return result;
}

async function followAction(tabId, label) {
  const before = await chrome.tabs.get(tabId);
  const knownTabIds = new Set((await chrome.tabs.query({ currentWindow: true })).map((tab) => tab.id));
  const action = await findPageAction(tabId, label);

  if (action.href) {
    const targetUrl = unwrapRedirectUrl(action.href);
    await chrome.tabs.update(tabId, { url: targetUrl, active: true });
    if (isTelegramLanding(targetUrl)) {
      // t.me tries to launch the tg:// protocol, so Chrome may never report the
      // tab as fully complete even though the OPEN IN WEB button is visible.
      await waitUntilInjectable(tabId);
    } else {
      await waitForTabComplete(tabId);
    }
    return tabId;
  }

  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    await sleep(350);
    const tabs = await chrome.tabs.query({ currentWindow: true });
    const newTab = tabs.find((tab) => !knownTabIds.has(tab.id));
    if (newTab?.id) {
      if (isTelegramLanding(newTab.url)) {
        await waitUntilInjectable(newTab.id);
      } else if (newTab.status !== "complete") {
        await waitForTabComplete(newTab.id);
      }
      await chrome.tabs.remove(tabId).catch(() => {});
      return newTab.id;
    }
    const current = await chrome.tabs.get(tabId);
    if (current.url !== before.url) {
      if (isTelegramLanding(current.url)) {
        await waitUntilInjectable(tabId);
      } else if (current.status !== "complete") {
        await waitForTabComplete(tabId);
      }
      return tabId;
    }
  }
  throw new Error(`Bấm ${label} nhưng trang không chuyển tiếp.`);
}

async function processUrl(url, pageWaitMs) {
  const tab = await chrome.tabs.create({ url, active: true });
  activeAutomationTabId = tab.id;
  await waitForTabComplete(tab.id);
  await sleep(pageWaitMs);

  let workingTabId = await followAction(tab.id, "Get Files (Alternate)");
  activeAutomationTabId = workingTabId;
  await sleep(pageWaitMs);
  let current = await chrome.tabs.get(workingTabId);

  if (!current.url?.startsWith("https://web.telegram.org/")) {
    workingTabId = await openTelegramWeb(workingTabId);
    activeAutomationTabId = workingTabId;
    current = await chrome.tabs.get(workingTabId);
  }

  if (!current.url?.startsWith("https://web.telegram.org/")) {
    throw new Error(`Đích cuối không phải Telegram Web: ${current.url || "không rõ"}`);
  }

  await sleep(2000);
  await chrome.tabs.remove(workingTabId).catch(() => {});
  activeAutomationTabId = null;
}

fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  queue = file ? parseUrls(await file.text()) : [];
  logEntries = [];
  logElement.replaceChildren();
  updateProgress(0);
  startButton.disabled = queue.length === 0;
  saveLogButton.disabled = true;
  setStatus(queue.length ? `Đã nạp ${queue.length} URL hợp lệ.` : "Không tìm thấy URL cbusters.com hợp lệ.");
});

startButton.addEventListener("click", async () => {
  stopRequested = false;
  startButton.disabled = true;
  stopButton.disabled = false;
  fileInput.disabled = true;
  delayInput.disabled = true;
  pageWaitInput.disabled = true;
  const delayMs = Math.max(1000, Number(delayInput.value || 2) * 1000);
  const pageWaitMs = Math.max(500, Number(pageWaitInput.value || 3) * 1000);

  for (let index = 0; index < queue.length; index += 1) {
    if (stopRequested) break;
    const url = queue[index];
    const startedAt = Date.now();
    setStatus(`Đang xử lý ${index + 1}/${queue.length} — 0 giây: ${url}`);
    const elapsedTimer = setInterval(() => {
      const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
      setStatus(`Đang xử lý ${index + 1}/${queue.length} — ${elapsedSeconds} giây: ${url}`);
    }, 1000);
    try {
      await processUrl(url, pageWaitMs);
      const elapsedSeconds = ((Date.now() - startedAt) / 1000).toFixed(1);
      appendLog(index + 1, "Thành công", url, `Đã mở trong Telegram Web (${elapsedSeconds} giây)`);
    } catch (error) {
      const elapsedSeconds = ((Date.now() - startedAt) / 1000).toFixed(1);
      appendLog(index + 1, "Lỗi", url, `${error.message || String(error)} (${elapsedSeconds} giây)`);
      if (activeAutomationTabId) {
        await chrome.tabs.remove(activeAutomationTabId).catch(() => {});
        activeAutomationTabId = null;
      }
    } finally {
      clearInterval(elapsedTimer);
    }
    updateProgress(index + 1);
    if (!stopRequested && index < queue.length - 1) await sleep(delayMs);
  }

  setStatus(stopRequested ? "Đã dừng theo yêu cầu." : "Đã xử lý xong danh sách.");
  startButton.disabled = false;
  stopButton.disabled = true;
  fileInput.disabled = false;
  delayInput.disabled = false;
  pageWaitInput.disabled = false;
});

stopButton.addEventListener("click", async () => {
  stopRequested = true;
  stopButton.disabled = true;
  setStatus("Đang dừng sau bước hiện tại…");
  if (activeAutomationTabId) {
    await chrome.tabs.remove(activeAutomationTabId).catch(() => {});
    activeAutomationTabId = null;
  }
});

saveLogButton.addEventListener("click", async () => {
  const escapeCsv = (value) => `"${String(value).replaceAll('"', '""')}"`;
  const rows = [["index", "status", "url", "detail"], ...logEntries.map((entry) =>
    [entry.index, entry.status, entry.url, entry.detail]
  )];
  const csv = rows.map((row) => row.map(escapeCsv).join(",")).join("\r\n") + "\r\n";
  await chrome.downloads.download({
    url: `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`,
    filename: `telegram-bot-run-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`,
    saveAs: true
  });
});
