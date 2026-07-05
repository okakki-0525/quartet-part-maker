const verticalScale = document.getElementById("verticalScale");
const gapMm = document.getElementById("gapMm");
const memoryPart = document.getElementById("memoryPart");
const memoryStart = document.getElementById("memoryStart");
const memoryClear = document.getElementById("memoryClear");
const memoryFileInput = document.getElementById("memoryFileInput");
const memoryProcessNow = document.getElementById("memoryProcessNow");
const memoryNext = document.getElementById("memoryNext");
const memoryFinish = document.getElementById("memoryFinish");
const nextWarning = document.getElementById("nextWarning");
const memoryStatus = document.getElementById("memoryStatus");
const busyMeter = document.getElementById("busyMeter");
const memoryDownloads = document.getElementById("memoryDownloads");
const registeredPages = document.getElementById("registeredPages");
const memoryDropZone = document.querySelector(".memory-upload");
const dropMain = document.getElementById("dropMain");
const dropSub = document.getElementById("dropSub");

let memorySessionId = null;
let memoryState = null;
let lastReadyPageCount = 0;
let waitingForNextPage = false;

function setMemoryStatus(message, isError = false) {
  memoryStatus.textContent = message;
  memoryStatus.classList.toggle("error", isError);
}

function setBusy(isBusy) {
  busyMeter.hidden = !isBusy;
}

function setDropText(main, sub, isError = false) {
  dropMain.textContent = main;
  dropSub.textContent = sub;
  memoryDropZone.classList.toggle("drop-error", isError);
}

function resetDropText() {
  setDropText("次の画像を追加", "クリックまたはドラッグ＆ドロップで1ページずつ登録");
}

function selectedPartLabel() {
  const part = memoryState ? memoryState.part : memoryPart.value;
  return `パート${part}`;
}

function currentCount() {
  return memoryState ? Number(memoryState.current_count || 0) : 0;
}

function currentPageNumber() {
  return memoryState ? Number(memoryState.page_number || 1) : 1;
}

function currentPageProgressMessage() {
  return `${selectedPartLabel()}の${currentPageNumber()}ページ目の${currentCount()}段目まで抽出しました。`;
}

function updateRegisteredPages() {
  const count = memoryState ? Number(memoryState.uploaded_pages || 0) : 0;
  registeredPages.textContent = `スコア${count}ページを登録しました。`;
}

function updateMemoryControls() {
  const active = Boolean(memorySessionId);
  const hasCurrentCrops = currentCount() > 0;

  memoryFileInput.disabled = waitingForNextPage;
  memoryProcessNow.disabled = !active || waitingForNextPage || !hasCurrentCrops;
  memoryNext.hidden = !waitingForNextPage;
  memoryNext.disabled = !waitingForNextPage;
  nextWarning.hidden = !waitingForNextPage;
  memoryFinish.hidden = !waitingForNextPage || !hasCurrentCrops;
  memoryFinish.disabled = !waitingForNextPage || !hasCurrentCrops;
  memoryStart.disabled = active;
  memoryPart.disabled = active;
  verticalScale.disabled = active;
  gapMm.disabled = active;
}

function latestUsableReadyPage() {
  if (!memoryState) return null;
  const pages = memoryState.ready_pages || [];
  for (let index = pages.length - 1; index >= 0; index -= 1) {
    if (!pages[index].discarded) return pages[index];
  }
  return null;
}

function renderProgress(defaultMessage = "") {
  if (!memoryState) {
    setMemoryStatus(defaultMessage || "画像を登録すると、自動で作成を開始します。");
    return;
  }

  const part = selectedPartLabel();
  const readyPages = memoryState.ready_pages || [];
  const latestReady = latestUsableReadyPage();

  if (readyPages.length > lastReadyPageCount && latestReady) {
    waitingForNextPage = true;
    setMemoryStatus(
      `${part}の${latestReady.page}ページ目が作成できるようになりました。まだ入りきらなかった段があるので次ページの先頭に入れます。`
    );
    setDropText("ページが完成しました", "PDFをダウンロードしてから次ページへ進んでください");
    lastReadyPageCount = readyPages.length;
    updateMemoryControls();
    return;
  }

  if (defaultMessage) {
    setMemoryStatus(defaultMessage);
    return;
  }

  setMemoryStatus(currentPageProgressMessage());
}

function renderMemoryDownloads() {
  memoryDownloads.innerHTML = "";
  if (!memorySessionId || !memoryState) return;

  memoryState.ready_pages.forEach((page) => {
    if (page.discarded) {
      const disabled = document.createElement("span");
      disabled.textContent = `パート${memoryState.part} ${page.page}ページ目は破棄されました`;
      disabled.className = "download-link disabled";
      memoryDownloads.appendChild(disabled);
      return;
    }

    const link = document.createElement("a");
    link.href = `/memory/${memorySessionId}/download/${page.page}`;
    link.textContent = `パート${memoryState.part} ${page.page}ページ目をダウンロード`;
    link.className = "download-link";
    memoryDownloads.appendChild(link);
  });
}

async function startMemoryMode() {
  if (memorySessionId) return true;

  const formData = new FormData();
  formData.append("part", memoryPart.value);
  formData.append("vertical_scale", verticalScale.value);
  formData.append("gap_mm", gapMm.value);
  setMemoryStatus("作成を開始しています。");
  setBusy(true);

  try {
    const response = await fetch("/memory/start", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "作成を開始できませんでした。");

    memorySessionId = data.session_id;
    memoryState = data.state;
    lastReadyPageCount = 0;
    waitingForNextPage = false;
    updateRegisteredPages();
    renderMemoryDownloads();
    renderProgress(currentPageProgressMessage());
    resetDropText();
    return true;
  } catch (error) {
    setMemoryStatus(error.message, true);
    return false;
  } finally {
    setBusy(false);
    updateMemoryControls();
  }
}

async function addMemoryImages(files) {
  const selected = Array.from(files).filter((file) => file.type.startsWith("image/"));
  if (selected.length === 0) return;

  if (selected.length > 1) {
    setDropText("画像は1枚ずつ登録してください", "2枚以上は登録されませんでした", true);
    return;
  }

  if (waitingForNextPage) {
    setDropText("次ページへ進んでください", "先に「次のページを作成する」を押してください", true);
    return;
  }

  const started = await startMemoryMode();
  if (!started || !memorySessionId) return;

  const formData = new FormData();
  formData.append("images", selected[0], selected[0].name);
  memoryFileInput.disabled = true;
  memoryProcessNow.disabled = true;
  setDropText("画像を処理しています", selected[0].name);
  setMemoryStatus("画像を処理しています。");
  setBusy(true);

  try {
    const response = await fetch(`/memory/${memorySessionId}/add`, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "画像の処理に失敗しました。");

    memoryState = data.state;
    updateRegisteredPages();
    renderMemoryDownloads();
    resetDropText();
    renderProgress();
  } catch (error) {
    setMemoryStatus(error.message, true);
    setDropText("画像の処理に失敗しました", "別の画像で試してください", true);
  } finally {
    setBusy(false);
    updateMemoryControls();
  }
}

async function finalizeCurrentPage(statusWhileWorking, noCropMessage) {
  if (!memorySessionId || currentCount() === 0) {
    setMemoryStatus(noCropMessage);
    return;
  }

  setMemoryStatus(statusWhileWorking);
  setBusy(true);
  try {
    const response = await fetch(`/memory/${memorySessionId}/finish`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "PDFにできませんでした。");

    const previousReadyCount = memoryState ? memoryState.ready_pages.length : 0;
    memoryState = data.state;
    lastReadyPageCount = previousReadyCount;
    waitingForNextPage = false;
    updateRegisteredPages();
    renderMemoryDownloads();
    resetDropText();

    const latestReady = latestUsableReadyPage();
    if (latestReady && memoryState.ready_pages.length > previousReadyCount) {
      setMemoryStatus(`パート${memoryState.part}の${latestReady.page}ページ目が作成できるようになりました。`);
      lastReadyPageCount = memoryState.ready_pages.length;
    } else {
      renderProgress(noCropMessage);
    }
  } catch (error) {
    setMemoryStatus(error.message, true);
  } finally {
    setBusy(false);
    updateMemoryControls();
  }
}

async function processNow() {
  await finalizeCurrentPage("現時点で溜まっている段をPDFにしています。", "処理できる段はまだありません。");
}

async function finishRemaining() {
  await finalizeCurrentPage("余った段をPDFにしています。", "余った段はありません。");
}

async function continueNextPage() {
  if (!memorySessionId || !waitingForNextPage) return;

  setMemoryStatus("現在のパート譜を破棄して、次ページの作業に進みます。");
  setBusy(true);
  try {
    const response = await fetch(`/memory/${memorySessionId}/discard-latest`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "現在のパート譜を破棄できませんでした。");

    memoryState = data.state;
    waitingForNextPage = false;
    renderMemoryDownloads();
    resetDropText();
    renderProgress(currentPageProgressMessage());
  } catch (error) {
    setMemoryStatus(error.message, true);
  } finally {
    setBusy(false);
    updateMemoryControls();
  }
}

async function clearMemoryMode() {
  if (memorySessionId) {
    await fetch(`/memory/${memorySessionId}/clear`, { method: "POST" }).catch(() => {});
  }

  memorySessionId = null;
  memoryState = null;
  lastReadyPageCount = 0;
  waitingForNextPage = false;
  memoryDownloads.innerHTML = "";
  updateRegisteredPages();
  resetDropText();
  setMemoryStatus("画像を登録すると、自動で作成を開始します。");
  updateMemoryControls();
}

memoryStart.addEventListener("click", startMemoryMode);
memoryClear.addEventListener("click", clearMemoryMode);
memoryProcessNow.addEventListener("click", processNow);
memoryNext.addEventListener("click", continueNextPage);
memoryFinish.addEventListener("click", finishRemaining);
memoryFileInput.addEventListener("change", () => {
  addMemoryImages(memoryFileInput.files);
  memoryFileInput.value = "";
});

memoryDropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!waitingForNextPage) {
    memoryDropZone.classList.add("dragover");
  }
});

memoryDropZone.addEventListener("dragleave", () => {
  memoryDropZone.classList.remove("dragover");
});

memoryDropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  memoryDropZone.classList.remove("dragover");
  addMemoryImages(event.dataTransfer.files);
});

resetDropText();
updateRegisteredPages();
updateMemoryControls();
