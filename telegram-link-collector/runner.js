const fileInput = document.querySelector("#file");
const delayInput = document.querySelector("#delay");
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

function waitForTabComplete(tabId, timeoutMs = 30000) {
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

async function findPageAction(tabId, expectedText) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: async (label) => {
      const normalize = (value) => (value || "").replace(/\s+/g, " ").trim().toLowerCase();
      const expected = normalize(label);
      const deadline = Date.now() + 15000;

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
    args: [expectedText]
  });
  if (!result || result.error) throw new Error(result?.error || `Không tìm thấy ${expectedText}.`);
  return result;
}

async function followAction(tabId, label) {
  const before = await chrome.tabs.get(tabId);
  const knownTabIds = new Set((await chrome.tabs.query({ currentWindow: true })).map((tab) => tab.id));
  const action = await findPageAction(tabId, label);

  if (action.href) {
    await chrome.tabs.update(tabId, { url: action.href, active: true });
    await waitForTabComplete(tabId);
    return tabId;
  }

  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    await sleep(350);
    const tabs = await chrome.tabs.query({ currentWindow: true });
    const newTab = tabs.find((tab) => !knownTabIds.has(tab.id));
    if (newTab?.id) {
      if (newTab.status !== "complete") await waitForTabComplete(newTab.id);
      await chrome.tabs.remove(tabId).catch(() => {});
      return newTab.id;
    }
    const current = await chrome.tabs.get(tabId);
    if (current.url !== before.url) {
      if (current.status !== "complete") await waitForTabComplete(tabId);
      return tabId;
    }
  }
  throw new Error(`Bấm ${label} nhưng trang không chuyển tiếp.`);
}

async function processUrl(url) {
  const tab = await chrome.tabs.create({ url, active: true });
  activeAutomationTabId = tab.id;
  await waitForTabComplete(tab.id);

  let workingTabId = await followAction(tab.id, "Get Files (Alternate)");
  activeAutomationTabId = workingTabId;
  let current = await chrome.tabs.get(workingTabId);

  if (!current.url?.startsWith("https://web.telegram.org/")) {
    workingTabId = await followAction(workingTabId, "OPEN IN WEB");
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
  const delayMs = Math.max(1000, Number(delayInput.value || 2) * 1000);

  for (let index = 0; index < queue.length; index += 1) {
    if (stopRequested) break;
    const url = queue[index];
    setStatus(`Đang xử lý ${index + 1}/${queue.length}: ${url}`);
    try {
      await processUrl(url);
      appendLog(index + 1, "Thành công", url, "Đã mở trong Telegram Web");
    } catch (error) {
      appendLog(index + 1, "Lỗi", url, error.message || String(error));
      if (activeAutomationTabId) {
        await chrome.tabs.remove(activeAutomationTabId).catch(() => {});
        activeAutomationTabId = null;
      }
    }
    updateProgress(index + 1);
    if (!stopRequested && index < queue.length - 1) await sleep(delayMs);
  }

  setStatus(stopRequested ? "Đã dừng theo yêu cầu." : "Đã xử lý xong danh sách.");
  startButton.disabled = false;
  stopButton.disabled = true;
  fileInput.disabled = false;
  delayInput.disabled = false;
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
