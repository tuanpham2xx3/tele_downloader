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
const compareBotButton = document.querySelector("#compareBot");
const saveMissingButton = document.querySelector("#saveMissing");
const compareStatusElement = document.querySelector("#compareStatus");
const compareLogElement = document.querySelector("#compareLog");
const compareResultsElement = document.querySelector(".compare-results");

let queue = [];
let logEntries = [];
let stopRequested = false;
let activeAutomationTabId = null;
let comparisonEntries = [];

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function parseUrls(text) {
  const entries = text.split(/\r?\n/).map((line) => {
    const match = line.match(/https:\/\/[^\s]+/i);
    if (!match) return null;
    const title = line.slice(0, match.index).replace(/[\t|—-]+\s*$/, "").trim();
    return { title, url: match[0] };
  }).filter(Boolean);

  const uniqueEntries = new Map();
  for (const entry of entries) {
    try {
      const url = new URL(entry.url);
      if (url.protocol === "https:" && url.hostname === "www.cbusters.com") {
        const existing = uniqueEntries.get(entry.url);
        if (!existing || (!existing.title && entry.title)) uniqueEntries.set(entry.url, entry);
      }
    } catch {
      // Ignore malformed lines.
    }
  }
  return [...uniqueEntries.values()];
}

function setStatus(message) {
  statusElement.textContent = message;
}

function updateProgress(completed) {
  completedElement.textContent = String(completed);
  totalElement.textContent = String(queue.length);
  progressBar.style.width = queue.length ? `${(completed / queue.length) * 100}%` : "0%";
}

function formatOpenedAt(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())} ${date.getMonth() + 1}/${date.getDate()}/${date.getFullYear()}`;
}

function appendLog(index, openedAt, status, title, url, detail) {
  const entry = { index, openedAt, status, title, url, detail };
  logEntries.push(entry);
  const row = document.createElement("tr");
  for (const [value, className] of [
    [index, ""],
    [openedAt, ""],
    [status, status === "Thành công" ? "success" : "failed"],
    [title || "—", ""],
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

function normalizeCourseTitle(value) {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function diceScore(first, second) {
  if (first === second) return 1;
  if (first.length < 2 || second.length < 2) return 0;
  const pairs = new Map();
  for (let index = 0; index < first.length - 1; index += 1) {
    const pair = first.slice(index, index + 2);
    pairs.set(pair, (pairs.get(pair) || 0) + 1);
  }
  let overlap = 0;
  for (let index = 0; index < second.length - 1; index += 1) {
    const pair = second.slice(index, index + 2);
    const count = pairs.get(pair) || 0;
    if (count > 0) {
      pairs.set(pair, count - 1);
      overlap += 1;
    }
  }
  return (2 * overlap) / (first.length + second.length - 2);
}

function compareCourseTitles(sourceEntries, botTitles) {
  const candidates = botTitles.map((title) => ({
    title,
    normalized: normalizeCourseTitle(title)
  })).filter((entry) => entry.normalized);

  return sourceEntries.map((source) => {
    const normalizedSource = normalizeCourseTitle(source.title);
    let best = { title: "", normalized: "", score: 0 };
    for (const candidate of candidates) {
      let score = diceScore(normalizedSource, candidate.normalized);
      const shorter = Math.min(normalizedSource.length, candidate.normalized.length);
      const longer = Math.max(normalizedSource.length, candidate.normalized.length);
      if ((normalizedSource.includes(candidate.normalized) || candidate.normalized.includes(normalizedSource)) &&
          shorter / Math.max(longer, 1) >= 0.85) {
        score = Math.max(score, 0.95);
      }
      if (score > best.score) best = { ...candidate, score };
    }

    const exact = best.normalized === normalizedSource;
    const status = exact ? "Có" : best.score >= 0.84 ? "Gần giống" : "Thiếu";
    return {
      status,
      sourceTitle: source.title,
      matchedTitle: status === "Thiếu" ? "" : best.title,
      score: best.score,
      url: source.url
    };
  });
}

async function scanBotCourseTitles() {
  const titles = new Set();
  const sleepInsidePage = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  function collectVisibleTitles() {
    const messages = document.querySelectorAll(
      ".bubble, .Message, [data-message-id], [id^='message']"
    );
    for (const message of messages) {
      const boldElements = message.querySelectorAll("strong, b, .text-bold");
      for (const element of boldElements) {
        const title = (element.textContent || "").replace(/\s+/g, " ").trim();
        if (title.length < 6 || title.length > 300) continue;
        if (/^(artist|audio|subtitles?|course material|course webpage|hashtag|for files|get files)\b/i.test(title)) continue;
        titles.add(title);
      }
    }
  }

  function findScroller() {
    const message = document.querySelector(".bubble, .Message, [data-message-id], [id^='message']");
    for (let current = message?.parentElement; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (/(auto|scroll)/.test(style.overflowY) && current.scrollHeight > current.clientHeight + 100) {
        return current;
      }
    }
    for (const selector of [".bubbles", ".MessageList", ".messages-container", "#MiddleColumn .scrollable"]) {
      const element = document.querySelector(selector);
      if (element && element.scrollHeight > element.clientHeight + 100) return element;
    }
    return null;
  }

  collectVisibleTitles();
  const scroller = findScroller();
  if (!scroller) return { titles: [...titles], error: "Không tìm thấy lịch sử tin nhắn của bot." };

  let unchangedRounds = 0;
  let previousFingerprint = "";
  for (let round = 0; round < 400 && unchangedRounds < 6; round += 1) {
    collectVisibleTitles();
    scroller.scrollTop = 0;
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    await sleepInsidePage(800);
    collectVisibleTitles();
    const text = (scroller.innerText || "").replace(/\s+/g, " ");
    const fingerprint = `${scroller.scrollHeight}|${text.slice(0, 500)}|${text.slice(-500)}`;
    if (fingerprint === previousFingerprint && scroller.scrollTop === 0) unchangedRounds += 1;
    else unchangedRounds = 0;
    previousFingerprint = fingerprint;
  }
  return { titles: [...titles] };
}

function renderComparison(entries) {
  compareLogElement.replaceChildren();
  for (const entry of entries) {
    const row = document.createElement("tr");
    const statusClass = entry.status === "Có" ? "present" : entry.status === "Gần giống" ? "near" : "missing";
    const values = [
      [entry.status, statusClass],
      [entry.sourceTitle, ""],
      [entry.matchedTitle || "—", ""],
      [entry.url, ""]
    ];
    for (const [value, className] of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (className) cell.className = className;
      row.appendChild(cell);
    }
    compareLogElement.appendChild(row);
  }
  compareResultsElement.classList.add("visible");
}

fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  queue = file ? parseUrls(await file.text()) : [];
  logEntries = [];
  logElement.replaceChildren();
  updateProgress(0);
  startButton.disabled = queue.length === 0;
  compareBotButton.disabled = !queue.some((entry) => entry.title);
  saveMissingButton.disabled = true;
  comparisonEntries = [];
  compareLogElement.replaceChildren();
  compareResultsElement.classList.remove("visible");
  compareStatusElement.textContent = compareBotButton.disabled
    ? "File này không có tên khóa học để đối chiếu."
    : `Sẵn sàng đối chiếu ${queue.filter((entry) => entry.title).length} tên khóa học.`;
  saveLogButton.disabled = true;
  setStatus(queue.length ? `Đã nạp ${queue.length} URL hợp lệ.` : "Không tìm thấy URL cbusters.com hợp lệ.");
});

compareBotButton.addEventListener("click", async () => {
  const sourceEntries = queue.filter((entry) => entry.title);
  if (!sourceEntries.length) return;

  compareBotButton.disabled = true;
  saveMissingButton.disabled = true;
  compareStatusElement.textContent = "Đang tìm tab bot Telegram Web…";
  const runnerTab = await chrome.tabs.getCurrent();

  try {
    const telegramTabs = await chrome.tabs.query({ url: "https://web.telegram.org/*" });
    const botTab = telegramTabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
    if (!botTab?.id) {
      throw new Error("Hãy mở chat bot trong một tab Telegram Web trước.");
    }

    compareStatusElement.textContent = "Đang cuộn lịch sử và đọc tên in đậm trong bot…";
    await chrome.tabs.update(botTab.id, { active: true });
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: botTab.id },
      func: scanBotCourseTitles
    });
    if (result?.error && !result.titles?.length) throw new Error(result.error);

    comparisonEntries = compareCourseTitles(sourceEntries, result?.titles || []);
    renderComparison(comparisonEntries);
    const present = comparisonEntries.filter((entry) => entry.status === "Có").length;
    const near = comparisonEntries.filter((entry) => entry.status === "Gần giống").length;
    const missing = comparisonEntries.filter((entry) => entry.status === "Thiếu").length;
    compareStatusElement.textContent = `Đã dò ${result?.titles?.length || 0} tên trong bot: ${present} có, ${near} gần giống, ${missing} thiếu.`;
    saveMissingButton.disabled = false;
  } catch (error) {
    compareStatusElement.textContent = error.message || String(error);
  } finally {
    if (runnerTab?.id) await chrome.tabs.update(runnerTab.id, { active: true }).catch(() => {});
    compareBotButton.disabled = false;
  }
});

saveMissingButton.addEventListener("click", async () => {
  const escapeCsv = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = [
    ["status", "source_course_title", "matched_bot_title", "similarity", "url"],
    ...comparisonEntries.map((entry) => [
      entry.status,
      entry.sourceTitle,
      entry.matchedTitle,
      entry.score.toFixed(3),
      entry.url
    ])
  ];
  const csv = rows.map((row) => row.map(escapeCsv).join(",")).join("\r\n") + "\r\n";
  await chrome.downloads.download({
    url: `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`,
    filename: `telegram-course-comparison-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`,
    saveAs: true
  });
});

startButton.addEventListener("click", async () => {
  stopRequested = false;
  startButton.disabled = true;
  stopButton.disabled = false;
  fileInput.disabled = true;
  delayInput.disabled = true;
  pageWaitInput.disabled = true;
  const delayMs = Math.max(1000, Number(delayInput.value || 2) * 1000);
  const pageWaitMs = Math.max(500, Number(pageWaitInput.value || 10) * 1000);

  for (let index = 0; index < queue.length; index += 1) {
    if (stopRequested) break;
    const { title, url } = queue[index];
    const startedAt = Date.now();
    const openedAt = formatOpenedAt(new Date(startedAt));
    const displayName = title || url;
    setStatus(`Đang xử lý ${index + 1}/${queue.length} — mở lúc ${openedAt} — 0 giây: ${displayName}`);
    const elapsedTimer = setInterval(() => {
      const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
      setStatus(`Đang xử lý ${index + 1}/${queue.length} — mở lúc ${openedAt} — ${elapsedSeconds} giây: ${displayName}`);
    }, 1000);
    try {
      await processUrl(url, pageWaitMs);
      const elapsedSeconds = ((Date.now() - startedAt) / 1000).toFixed(1);
      appendLog(index + 1, openedAt, "Thành công", title, url, `Đã mở trong Telegram Web (${elapsedSeconds} giây)`);
    } catch (error) {
      const elapsedSeconds = ((Date.now() - startedAt) / 1000).toFixed(1);
      appendLog(index + 1, openedAt, "Lỗi", title, url, `${error.message || String(error)} (${elapsedSeconds} giây)`);
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
  const rows = [["index", "opened_at", "status", "course_title", "url", "detail"], ...logEntries.map((entry) =>
    [entry.index, entry.openedAt, entry.status, entry.title, entry.url, entry.detail]
  )];
  const csv = rows.map((row) => row.map(escapeCsv).join(",")).join("\r\n") + "\r\n";
  await chrome.downloads.download({
    url: `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`,
    filename: `telegram-bot-run-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`,
    saveAs: true
  });
});
