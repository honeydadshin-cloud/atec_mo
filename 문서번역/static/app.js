const TARGET = (window.TRANSLATE_CONFIG && window.TRANSLATE_CONFIG.target) || 'ko';

const sourceLang = document.getElementById('sourceLang');
const translateBtn = document.getElementById('translateBtn');
const resultBody = document.getElementById('resultBody');
const statusMsg = document.getElementById('statusMsg');
const copyBtn = document.getElementById('copyBtn');
const downloadBtn = document.getElementById('downloadBtn');
const toast = document.getElementById('toast');
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const fileName = document.getElementById('fileName');
const summaryCard = document.getElementById('summaryCard');
const summaryBody = document.getElementById('summaryBody');
const playTtsBtn = document.getElementById('playTtsBtn');
const stopTtsBtn = document.getElementById('stopTtsBtn');
const ttsStatus = document.getElementById('ttsStatus');

let selectedFile = null;
let translatedContent = '';
let downloadFilename = 'translated_ko.txt';
let summaryText = '';
let audioPlayer = null;

dropzone.addEventListener('click', () => fileInput.click());

dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropzone.classList.add('dragover');
});

dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files.length) setFile(fileInput.files[0]);
});

function setFile(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['txt', 'docx'].includes(ext)) {
    setStatus('TXT 또는 DOCX 파일만 업로드할 수 있습니다.', 'error');
    return;
  }
  selectedFile = file;
  fileName.textContent = `선택됨: ${file.name}`;
  setStatus('');
  resetSummary();
}

function setLoading(loading) {
  translateBtn.disabled = loading;
}

function setStatus(msg, type = '') {
  statusMsg.textContent = msg;
  statusMsg.className = `status-line ${type}`;
}

function setTtsStatus(msg, type = '') {
  ttsStatus.textContent = msg;
  ttsStatus.className = `tts-status ${type}`;
}

function setResult(text) {
  translatedContent = text;
  resultBody.textContent = text;
  copyBtn.disabled = false;
  downloadBtn.disabled = false;
}

function resetSummary() {
  summaryText = '';
  summaryCard.hidden = true;
  summaryBody.innerHTML = '<p class="empty-msg">요약을 생성하는 중...</p>';
  playTtsBtn.disabled = true;
  stopTtsBtn.disabled = true;
  setTtsStatus('');
  stopAudio();
}

function renderSummary(lines) {
  summaryBody.innerHTML = lines
    .map(
      (line, i) => `
        <div class="summary-line">
          <span class="summary-num">${i + 1}</span>
          <p>${escapeHtml(line)}</p>
        </div>`
    )
    .join('');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2500);
}

function stopAudio() {
  if (audioPlayer) {
    audioPlayer.pause();
    audioPlayer.currentTime = 0;
    if (audioPlayer.src.startsWith('blob:')) {
      URL.revokeObjectURL(audioPlayer.src);
    }
    audioPlayer = null;
  }
  playTtsBtn.disabled = !summaryText;
  stopTtsBtn.disabled = true;
}

async function playSummaryTts() {
  if (!summaryText) return;

  stopAudio();
  setTtsStatus('음성을 생성하는 중...', 'playing');
  playTtsBtn.disabled = true;

  try {
    const res = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: summaryText }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || '음성 생성에 실패했습니다.');
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    audioPlayer = new Audio(url);

    audioPlayer.addEventListener('ended', () => {
      setTtsStatus('음성 재생이 완료되었습니다.');
      stopTtsBtn.disabled = true;
      playTtsBtn.disabled = false;
      URL.revokeObjectURL(url);
      audioPlayer = null;
    });

    audioPlayer.addEventListener('error', () => {
      setTtsStatus('음성 재생 중 오류가 발생했습니다.', 'error');
      playTtsBtn.disabled = false;
      stopTtsBtn.disabled = true;
    });

    await audioPlayer.play();
    setTtsStatus('3줄 요약을 읽어 드리는 중...', 'playing');
    stopTtsBtn.disabled = false;
  } catch (err) {
    setTtsStatus(err.message, 'error');
    playTtsBtn.disabled = false;
  }
}

async function summarizeAndPlay(text) {
  resetSummary();
  summaryCard.hidden = false;
  setTtsStatus('Gemini로 3줄 요약 생성 중...', 'playing');

  try {
    const res = await fetch('/api/summarize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '요약 생성에 실패했습니다.');

    const lines = data.lines && data.lines.length ? data.lines : data.summary.split('\n').filter(Boolean);
    summaryText = lines.join('\n');
    renderSummary(lines.slice(0, 3));
    playTtsBtn.disabled = false;

    await playSummaryTts();
  } catch (err) {
    summaryBody.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
    setTtsStatus(err.message, 'error');
  }
}

translateBtn.addEventListener('click', async () => {
  setStatus('');
  resetSummary();

  if (!selectedFile) {
    setStatus('먼저 영문 텍스트 파일(.txt)을 업로드해 주세요.', 'error');
    return;
  }

  setLoading(true);
  setStatus('한국어로 번역하는 중...', 'playing');

  try {
    const form = new FormData();
    form.append('file', selectedFile);
    form.append('source', sourceLang.value);
    form.append('target', TARGET);

    const res = await fetch('/api/translate-file', {
      method: 'POST',
      body: form,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '번역에 실패했습니다.');

    setResult(data.result);
    downloadFilename = data.filename;
    setStatus(
      `${data.original_chars.toLocaleString()}자 번역 완료 · ${selectedFile.name}`,
      'success'
    );
    setLoading(false);

    await summarizeAndPlay(data.result);
  } catch (err) {
    setStatus(err.message, 'error');
    setLoading(false);
  }
});

copyBtn.addEventListener('click', async () => {
  if (!translatedContent) return;
  await navigator.clipboard.writeText(translatedContent);
  showToast('번역문이 복사되었습니다.');
});

downloadBtn.addEventListener('click', async () => {
  if (!translatedContent) return;

  const res = await fetch('/api/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content: translatedContent,
      filename: downloadFilename,
    }),
  });

  if (!res.ok) {
    showToast('저장에 실패했습니다.');
    return;
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = downloadFilename;
  a.click();
  URL.revokeObjectURL(url);
  showToast('한국어 번역 파일을 저장했습니다.');
});

playTtsBtn.addEventListener('click', playSummaryTts);
stopTtsBtn.addEventListener('click', () => {
  stopAudio();
  setTtsStatus('재생이 중지되었습니다.');
});
