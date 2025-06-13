const startBtn = document.querySelector("#start-btn");
const stopBtn = document.querySelector("#stop-btn");
const clearBtn = document.querySelector("#clear-btn");
const languageSelect = document.querySelector("#language-select");
const resultDiv = document.querySelector("#result-div");
const statusDiv = document.querySelector("#status-div");

let SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = new SpeechRecognition();

recognition.lang = languageSelect.value;
recognition.interimResults = true;
recognition.continuous = true;

let finalTranscript = "";

recognition.onstart = () => {
  statusDiv.textContent = "音声認識中...";
  statusDiv.style.backgroundColor = "#e8f5e9";
};

recognition.onend = () => {
  statusDiv.textContent = "待機中";
  statusDiv.style.backgroundColor = "#f0f0f0";
  startBtn.disabled = false;
  stopBtn.disabled = true;
};

recognition.onerror = (event) => {
  statusDiv.textContent = `エラー: ${event.error}`;
  statusDiv.style.backgroundColor = "#ffebee";
  startBtn.disabled = false;
  stopBtn.disabled = true;
};

recognition.onresult = async (event) => {
  let interimTranscript = "";
  for (let i = event.resultIndex; i < event.results.length; i++) {
    let transcript = event.results[i][0].transcript;
    if (event.results[i].isFinal) {
      finalTranscript += transcript;
      resultDiv.innerHTML = finalTranscript;

      // デモ関数を使用して応答取得・音声出力
      const reply = await sendToGeminiDemo(finalTranscript);
      speakText(reply);
    } else {
      interimTranscript = transcript;
      resultDiv.innerHTML =
        finalTranscript +
        '<i style="color:#666;">' +
        interimTranscript +
        "</i>";
    }
  }
};

languageSelect.onchange = () => {
  recognition.lang = languageSelect.value;
};

startBtn.onclick = () => {
  recognition.start();
  startBtn.disabled = true;
  stopBtn.disabled = false;
};

stopBtn.onclick = () => {
  recognition.stop();
  startBtn.disabled = false;
  stopBtn.disabled = true;
};

clearBtn.onclick = () => {
  finalTranscript = "";
  resultDiv.innerHTML = "";
};

async function sendToGeminiDemo(promptText) {
  console.log("受信テキスト:", promptText);
  response_text = "hello"; // デモ用の固定応答
  console.log("応答:", response_text);
  return response_text; // デモ用の固定応答を返す
}

function speakText(text) {
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = languageSelect.value;
  speechSynthesis.speak(utterance);
}
