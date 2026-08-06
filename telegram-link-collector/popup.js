const statusElement = document.querySelector("#status");
const resultsElement = document.querySelector("#results");
const scanVisibleButton = document.querySelector("#scanVisible");
const scanHistoryButton = document.querySelector("#scanHistory");
const copyButton = document.querySelector("#copy");
const saveButton = document.querySelector("#save");
const openRunnerButton = document.querySelector("#openRunner");

let collectedEntries = [];

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
              return text.length > 3 && !text.toLowerCase().includes("get files");
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

openRunnerButton.addEventListener("click", async () => {
  await chrome.tabs.create({ url: chrome.runtime.getURL("runner.html") });
});
