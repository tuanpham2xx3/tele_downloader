const statusElement = document.querySelector("#status");
const resultsElement = document.querySelector("#results");
const scanVisibleButton = document.querySelector("#scanVisible");
const scanHistoryButton = document.querySelector("#scanHistory");
const copyButton = document.querySelector("#copy");
const saveButton = document.querySelector("#save");

let collectedUrls = [];

function showStatus(message, isError = false) {
  statusElement.textContent = message;
  statusElement.classList.toggle("error", isError);
}

function setBusy(isBusy) {
  scanVisibleButton.disabled = isBusy;
  scanHistoryButton.disabled = isBusy;
}

function renderResults(urls) {
  collectedUrls = [...new Set(urls)].sort();
  resultsElement.value = collectedUrls.join("\n");
  copyButton.disabled = collectedUrls.length === 0;
  saveButton.disabled = collectedUrls.length === 0;
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

    renderResults(result.urls);
    showStatus(`Đã tìm thấy ${result.urls.length} URL duy nhất.`);
  } catch (error) {
    showStatus(error.message || String(error), true);
  } finally {
    setBusy(false);
  }
}

async function collectGetFilesUrls(scanHistory) {
  const urls = new Set();
  const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  function collectVisible() {
    for (const anchor of document.querySelectorAll("a[href]")) {
      const label = (anchor.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (label === "get files" || label.includes("get files")) {
        try {
          const url = new URL(anchor.href, location.href);
          if (url.protocol === "http:" || url.protocol === "https:") {
            urls.add(url.href);
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
    return { urls: [...urls] };
  }

  const scroller = findMessageScroller();
  if (!scroller) {
    return { urls: [...urls], error: "Không tìm thấy vùng tin nhắn có thể cuộn." };
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

  return { urls: [...urls] };
}

scanVisibleButton.addEventListener("click", () => runCollector(false));
scanHistoryButton.addEventListener("click", () => runCollector(true));

copyButton.addEventListener("click", async () => {
  await navigator.clipboard.writeText(collectedUrls.join("\n"));
  showStatus(`Đã sao chép ${collectedUrls.length} URL.`);
});

saveButton.addEventListener("click", async () => {
  const contents = collectedUrls.join("\r\n") + "\r\n";
  const dataUrl = `data:text/plain;charset=utf-8,${encodeURIComponent(contents)}`;
  await chrome.downloads.download({
    url: dataUrl,
    filename: `telegram-get-files-${new Date().toISOString().replace(/[:.]/g, "-")}.txt`,
    saveAs: true
  });
  showStatus(`Đã tạo file chứa ${collectedUrls.length} URL.`);
});
