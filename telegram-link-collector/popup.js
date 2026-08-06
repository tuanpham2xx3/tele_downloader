const statusElement = document.querySelector("#status");
const resultsElement = document.querySelector("#results");
const scanVisibleButton = document.querySelector("#scanVisible");
const scanHistoryButton = document.querySelector("#scanHistory");
const copyButton = document.querySelector("#copy");
const saveButton = document.querySelector("#save");
const openRunnerButton = document.querySelector("#openRunner");
const sourceFileInput = document.querySelector("#sourceFile");
const compareCurrentBotButton = document.querySelector("#compareCurrentBot");
const saveComparisonButton = document.querySelector("#saveComparison");
const compareStatusElement = document.querySelector("#compareStatus");

let collectedEntries = [];
let sourceEntries = [];
let comparisonEntries = [];

function showStatus(message, isError = false) {
  statusElement.textContent = message;
  statusElement.classList.toggle("error", isError);
}

function setBusy(isBusy) {
  scanVisibleButton.disabled = isBusy;
  scanHistoryButton.disabled = isBusy;
}

function renderResults(entries) {
  const uniqueEntries = new Map();
  for (const entry of entries) {
    const existing = uniqueEntries.get(entry.url);
    if (!existing || (!existing.title && entry.title)) uniqueEntries.set(entry.url, entry);
  }
  collectedEntries = [...uniqueEntries.values()].sort((a, b) =>
    (a.title || a.url).localeCompare(b.title || b.url)
  );
  resultsElement.value = collectedEntries.map((entry) =>
    entry.title ? `${entry.title}\t${entry.url}` : entry.url
  ).join("\n");
  copyButton.disabled = collectedEntries.length === 0;
  saveButton.disabled = collectedEntries.length === 0;
}

async function runCollector(scanHistory) {
  setBusy(true);
  showStatus(scanHistory ? "Đang cuộn và quét lịch sử…" : "Đang quét…");

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !tab.url?.startsWith("https://web.telegram.org/")) {
      throw new Error("Hãy mở group con trong Telegram Web trước.");
    }

    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: collectGetFilesUrls,
      args: [scanHistory]
    });

    if (result.error) {
      throw new Error(result.error);
    }

    renderResults(result.entries);
    showStatus(`Đã tìm thấy ${result.entries.length} khóa học/URL duy nhất.`);
  } catch (error) {
    showStatus(error.message || String(error), true);
  } finally {
    setBusy(false);
  }
}

async function collectGetFilesUrls(scanHistory) {
  const entries = new Map();
  const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  function collectVisible() {
    for (const anchor of document.querySelectorAll("a[href]")) {
      const label = (anchor.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (label === "get files" || label.includes("get files")) {
        try {
          const url = new URL(anchor.href, location.href);
          if (url.protocol === "http:" || url.protocol === "https:") {
            const message = anchor.closest(
              ".bubble, .Message, [data-message-id], [id^='message']"
            );
            const boldElements = message ? [...message.querySelectorAll("strong, b, .text-bold")] : [];
            const titleElement = boldElements.find((element) => {
              const text = (element.textContent || "").replace(/\s+/g, " ").trim();
              return text.length > 5 &&
                !/^(artist|audio|subtitles?|course material|course webpage|hashtag|for files|get files)\b/i.test(text);
            });
            const title = (titleElement?.textContent || "").replace(/\s+/g, " ").trim();
            const existing = entries.get(url.href);
            if (!existing || (!existing.title && title)) {
              entries.set(url.href, { title, url: url.href });
            }
          }
        } catch {
          // Ignore malformed or non-web URLs.
        }
      }
    }
  }

  function findMessageScroller() {
    function scrollableAncestorOf(element) {
      for (let current = element?.parentElement; current; current = current.parentElement) {
        const style = getComputedStyle(current);
        if (/(auto|scroll)/.test(style.overflowY) && current.scrollHeight > current.clientHeight + 100) {
          return current;
        }
      }
      return null;
    }

    const getFilesLink = [...document.querySelectorAll("a[href]")].find((anchor) =>
      (anchor.textContent || "").toLowerCase().includes("get files")
    );
    const messageElement = getFilesLink || document.querySelector(
      ".bubble, .Message, [data-message-id], [id^='message']"
    );
    const ancestorScroller = scrollableAncestorOf(messageElement);
    if (ancestorScroller) {
      return ancestorScroller;
    }

    const preferred = [
      ".bubbles",
      ".MessageList",
      ".messages-container",
      ".chat-content .scrollable",
      "#MiddleColumn .scrollable"
    ];

    for (const selector of preferred) {
      const element = document.querySelector(selector);
      if (element && element.scrollHeight > element.clientHeight + 100) {
        return element;
      }
    }

    return [...document.querySelectorAll("div")]
      .filter((element) => {
        const style = getComputedStyle(element);
        return /(auto|scroll)/.test(style.overflowY) &&
          element.clientHeight > 250 &&
          element.scrollHeight > element.clientHeight + 300;
      })
      .sort((a, b) => b.clientHeight - a.clientHeight)[0] || null;
  }

  collectVisible();
  if (!scanHistory) {
    return { entries: [...entries.values()] };
  }

  const scroller = findMessageScroller();
  if (!scroller) {
    return { entries: [...entries.values()], error: "Không tìm thấy vùng tin nhắn có thể cuộn." };
  }

  let unchangedRounds = 0;
  let previousFingerprint = "";
  const maximumRounds = 300;

  for (let round = 0; round < maximumRounds && unchangedRounds < 5; round += 1) {
    collectVisible();
    scroller.scrollTop = 0;
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    await sleep(900);
    collectVisible();

    const visibleText = (scroller.innerText || "").replace(/\s+/g, " ");
    const fingerprint = [
      scroller.scrollHeight,
      visibleText.slice(0, 500),
      visibleText.slice(-500)
    ].join("|");

    if (fingerprint === previousFingerprint && scroller.scrollTop === 0) {
      unchangedRounds += 1;
    } else {
      unchangedRounds = 0;
    }
    previousFingerprint = fingerprint;
  }

  return { entries: [...entries.values()] };
}

function parseSourceEntries(text) {
  const uniqueEntries = new Map();
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/https:\/\/[^\s]+/i);
    if (!match) continue;
    const title = line.slice(0, match.index).replace(/[\t|—-]+\s*$/, "").trim();
    if (!title) continue;
    try {
      const url = new URL(match[0]);
      if (url.hostname !== "www.cbusters.com") continue;
      uniqueEntries.set(url.href, { title, url: url.href });
    } catch {
      // Ignore malformed lines.
    }
  }
  return [...uniqueEntries.values()];
}

function normalizeCourseTitle(value) {
  return value.normalize("NFKD")
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

function compareTitles(botTitles) {
  const candidates = botTitles.map((title) => ({ title, normalized: normalizeCourseTitle(title) }))
    .filter((entry) => entry.normalized);
  return sourceEntries.map((source) => {
    const normalizedSource = normalizeCourseTitle(source.title);
    let best = { title: "", normalized: "", score: 0 };
    for (const candidate of candidates) {
      let score = diceScore(normalizedSource, candidate.normalized);
      const shorter = Math.min(normalizedSource.length, candidate.normalized.length);
      const longer = Math.max(normalizedSource.length, candidate.normalized.length);
      if ((normalizedSource.includes(candidate.normalized) || candidate.normalized.includes(normalizedSource)) &&
          shorter / Math.max(longer, 1) >= 0.85) score = Math.max(score, 0.95);
      if (score > best.score) best = { ...candidate, score };
    }
    const status = best.normalized === normalizedSource ? "Có" : best.score >= 0.84 ? "Gần giống" : "Thiếu";
    return {
      status,
      sourceTitle: source.title,
      matchedTitle: status === "Thiếu" ? "" : best.title,
      score: best.score,
      url: source.url
    };
  });
}

async function scanCurrentBotTitles() {
  const titles = new Set();
  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  function collectVisible() {
    const messages = document.querySelectorAll(
      ".bubble, .Message, [data-message-id], [id^='message']"
    );
    for (const message of messages) {
      for (const element of message.querySelectorAll("strong, b, .text-bold")) {
        const title = (element.textContent || "").replace(/\s+/g, " ").trim();
        if (title.length < 6 || title.length > 300) continue;
        if (/^(artist|audio|subtitles?|course material|course webpage|hashtag|for files|get files)\b/i.test(title)) continue;
        titles.add(title);
      }
    }
  }

  function scrollableAncestorOf(element) {
    for (let current = element?.parentElement; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (/(auto|scroll)/.test(style.overflowY) && current.scrollHeight > current.clientHeight + 100) {
        return current;
      }
    }
    return null;
  }

  function findMessageScroller() {
    const titleElement = document.querySelector(
      ".bubble strong, .bubble b, .bubble .text-bold, .Message strong, .Message b, .Message .text-bold"
    );
    const messageElement = titleElement || document.querySelector(
      ".bubble, .Message, [data-message-id], [id^='message']"
    );
    const ancestor = scrollableAncestorOf(messageElement);
    if (ancestor) return ancestor;

    for (const selector of [
      ".bubbles",
      ".MessageList",
      ".messages-container",
      ".chat-content .scrollable",
      "#MiddleColumn .scrollable"
    ]) {
      const element = document.querySelector(selector);
      if (element && element.scrollHeight > element.clientHeight + 100) return element;
    }
    return null;
  }

  collectVisible();
  const scroller = findMessageScroller();
  if (!scroller) return { titles: [...titles], error: "Không tìm thấy vùng tin nhắn có thể cuộn." };

  let unchangedRounds = 0;
  let previousFingerprint = "";
  for (let round = 0; round < 400 && unchangedRounds < 6; round += 1) {
    collectVisible();
    scroller.scrollTop = 0;
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    await wait(900);
    collectVisible();

    const visibleText = (scroller.innerText || "").replace(/\s+/g, " ");
    const fingerprint = [
      scroller.scrollHeight,
      visibleText.slice(0, 500),
      visibleText.slice(-500)
    ].join("|");
    if (fingerprint === previousFingerprint && scroller.scrollTop === 0) unchangedRounds += 1;
    else unchangedRounds = 0;
    previousFingerprint = fingerprint;
  }
  return { titles: [...titles] };
}

scanVisibleButton.addEventListener("click", () => runCollector(false));
scanHistoryButton.addEventListener("click", () => runCollector(true));

copyButton.addEventListener("click", async () => {
  await navigator.clipboard.writeText(resultsElement.value);
  showStatus(`Đã sao chép ${collectedEntries.length} khóa học/URL.`);
});

saveButton.addEventListener("click", async () => {
  const contents = collectedEntries.map((entry) =>
    entry.title ? `${entry.title}\t${entry.url}` : entry.url
  ).join("\r\n") + "\r\n";
  const dataUrl = `data:text/plain;charset=utf-8,${encodeURIComponent(contents)}`;
  await chrome.downloads.download({
    url: dataUrl,
    filename: `telegram-get-files-${new Date().toISOString().replace(/[:.]/g, "-")}.txt`,
    saveAs: true
  });
  showStatus(`Đã tạo file chứa ${collectedEntries.length} khóa học/URL.`);
});

sourceFileInput.addEventListener("change", async () => {
  const file = sourceFileInput.files?.[0];
  sourceEntries = file ? parseSourceEntries(await file.text()) : [];
  comparisonEntries = [];
  compareCurrentBotButton.disabled = sourceEntries.length === 0;
  saveComparisonButton.disabled = true;
  compareStatusElement.textContent = sourceEntries.length
    ? `Đã nạp ${sourceEntries.length} khóa học. Mở đúng bot rồi bấm dò.`
    : "File không có dòng Tên khóa học + URL hợp lệ.";
});

compareCurrentBotButton.addEventListener("click", async () => {
  compareCurrentBotButton.disabled = true;
  saveComparisonButton.disabled = true;
  compareStatusElement.textContent = "Đang cuộn và dò toàn bộ bot hiện tại…";

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !tab.url?.startsWith("https://web.telegram.org/")) {
      throw new Error("Hãy mở đúng chat bot trong Telegram Web trước.");
    }
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: scanCurrentBotTitles
    });
    if (result?.error && !result.titles?.length) throw new Error(result.error);

    comparisonEntries = compareTitles(result?.titles || []);
    const present = comparisonEntries.filter((entry) => entry.status === "Có").length;
    const near = comparisonEntries.filter((entry) => entry.status === "Gần giống").length;
    const missingEntries = comparisonEntries.filter((entry) => entry.status === "Thiếu");
    resultsElement.value = [
      ...missingEntries.map((entry) => `[THIẾU]\t${entry.sourceTitle}\t${entry.url}`),
      ...comparisonEntries.filter((entry) => entry.status === "Gần giống").map((entry) =>
        `[GẦN GIỐNG]\t${entry.sourceTitle}\t=> ${entry.matchedTitle}\t${entry.url}`
      )
    ].join("\n");
    copyButton.disabled = !resultsElement.value;
    saveButton.disabled = true;
    compareStatusElement.textContent = `Đã dò ${result?.titles?.length || 0} tên: ${present} có, ${near} gần giống, ${missingEntries.length} thiếu.`;
    saveComparisonButton.disabled = false;
  } catch (error) {
    compareStatusElement.textContent = error.message || String(error);
  } finally {
    compareCurrentBotButton.disabled = sourceEntries.length === 0;
  }
});

saveComparisonButton.addEventListener("click", async () => {
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

openRunnerButton.addEventListener("click", async () => {
  await chrome.tabs.create({ url: chrome.runtime.getURL("runner.html") });
});
