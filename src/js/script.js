const startBtn = document.querySelector("#start-btn");
const stopBtn = document.querySelector("#stop-btn");
const clearBtn = document.querySelector("#clear-btn");
const languageSelect = document.querySelector("#language-select");
const resultDiv = document.querySelector("#result-div");
const statusDiv = document.querySelector("#status-div");
const chatContainer = document.querySelector("#chat-container");
const navBar = document.querySelector("nav");
const userIdDisplay = document.querySelector("#user-id-display");
const ENDPOINT_HOST_URL = "https://resilience-interviewer.onrender.com"; // APIのホストURL
// Flag to track manual stop
let isManuallyStopped = false;
// Flag to track if we're waiting for server response
let isWaitingForResponse = false;

// セッションIDを固定
let currentSessionId = "";
let user_id = "";

// 音声認識のタイマー設定
let silenceTimer = null;
const SILENCE_TIMEOUT = 3000; // 3秒
let hasSpokenOnce = false; // ユーザーが一度でも話したかのフラグ
let isRecognizing = false; // 音声認識中かどうかのフラグ

// 音声認識の開始/停止を切り替える関数
function toggle_recog(shouldStart) {
  if (shouldStart && !isRecognizing) {
    // 音声認識を開始
    isRecognizing = true;
    recognition.start();
    startBtn.disabled = true;
    stopBtn.disabled = false;
    statusDiv.textContent = "音声認識中...";
    navBar.classList.remove("waiting", "error");
    navBar.classList.add("recognizing");
  } else if (!shouldStart && isRecognizing) {
    // 音声認識を停止
    isRecognizing = false;
    recognition.stop();
    startBtn.disabled = false;
    stopBtn.disabled = true;
    statusDiv.textContent = "待機中";
    navBar.classList.remove("recognizing", "error");
    navBar.classList.add("waiting");
  }
}

function resetSilenceTimer() {
  if (silenceTimer) {
    clearTimeout(silenceTimer);
  }
  silenceTimer = setTimeout(() => {
    console.log("3秒以上の沈黙を検出、音声認識を終了");
    toggle_recog(false);
  }, SILENCE_TIMEOUT);
}

function clearSilenceTimer() {
  if (silenceTimer) {
    clearTimeout(silenceTimer);
    silenceTimer = null;
  }
}

function appendMessage(text, sender) {
  const message = document.createElement("div");
  message.classList.add("chat-bubble", sender);
  message.textContent = text;
  chatContainer.appendChild(message);

  // 自動で最下部までスクロール（スムーズに）
  message.scrollIntoView({ behavior: "smooth", block: "end" });

  // Save history to localStorage
  const history = Array.from(chatContainer.children).map((node) => {
    return {
      role: node.classList.contains("user") ? "user" : "assistant",
      content: node.textContent,
    };
  });
  localStorage.setItem("chatHistory", JSON.stringify(history));
}

let SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = new SpeechRecognition();

recognition.lang = languageSelect.value;
recognition.interimResults = true;
recognition.continuous = true;

let finalTranscript = "";

recognition.onstart = () => {
  isRecognizing = true;
  clearSilenceTimer(); // タイマーをクリア
};

recognition.onend = () => {
  isRecognizing = false;
  clearSilenceTimer(); // タイマーをクリア
  if (!isManuallyStopped && !isWaitingForResponse) {
    toggle_recog(true); // Auto-restart
  } else {
    statusDiv.textContent = "待機中";
    navBar.classList.remove("recognizing", "error");
    navBar.classList.add("waiting");
    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
};

recognition.onerror = (event) => {
  statusDiv.textContent = `エラー: ${event.error}`;
  navBar.classList.remove("recognizing", "waiting");
  navBar.classList.add("error");
  isRecognizing = false;
  clearSilenceTimer(); // タイマーをクリア
  // エラー時も手動停止でない限りボタンの状態を維持
  if (isManuallyStopped) {
    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
};

recognition.onresult = async (event) => {
  for (let i = event.resultIndex; i < event.results.length; i++) {
    let transcript = event.results[i][0].transcript;
    if (event.results[i].isFinal) {
      finalTranscript += transcript;

      // 空文字や空白のみの場合はスキップ
      if (transcript.trim().length > 0) {
        appendMessage(transcript, "user");
        clearSilenceTimer(); // 最終結果でタイマーをクリア

        // サーバーレスポンス待ち中は音声認識を停止
        isWaitingForResponse = true;
        toggle_recog(false);

        const reply = await sendToInterviewer(finalTranscript);
        appendMessage(reply, "assistant");
        speakText(reply);

        // レスポンス完了後、音声認識を再開
        isWaitingForResponse = false;
        if (!isManuallyStopped) {
          toggle_recog(true);
        }
      }
    } else {
      // 実際に音声がある場合のみタイマーをリセット
      if (transcript.trim().length > 0) {
        resetSilenceTimer(); // 中間結果でタイマーをリセット
      }
    }
  }
};

languageSelect.onchange = () => {
  recognition.lang = languageSelect.value;
};

startBtn.onclick = () => {
  isManuallyStopped = false;
  toggle_recog(true);

  // 初回開始時の挨拶メッセージ（履歴がない場合のみ）
  const saved = localStorage.getItem("chatHistory");
  if (!saved) {
    const initMessage = "先ほどはどんな業務をしていたのですか？";
    appendMessage(initMessage, "assistant");
    speakText(initMessage);
  }
};

stopBtn.onclick = () => {
  isManuallyStopped = true;
  toggle_recog(false);
};

clearBtn.onclick = () => {
  finalTranscript = "";
  chatContainer.innerHTML = "";
  localStorage.removeItem("chatHistory");
  currentSessionId = "audio_session_" + Date.now();
  console.log("履歴をクリアしました");
};

async function sendToInterviewer(promptText) {
  console.log("受信テキスト:", promptText);

  try {
    const response = await fetch(`${ENDPOINT_HOST_URL}/audio_interview`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text: promptText,
        session_id: currentSessionId, // 固定のセッションIDを使用
        user_id: user_id,
      }),
    });

    if (!response.ok) {
      const errorMessage = `通信エラーが発生しました (ステータス: ${response.status})`;
      console.error(errorMessage);
      return errorMessage;
    }

    const data = await response.json();
    const response_text = data.response;
    console.log("応答:", response_text);
    return response_text;
  } catch (error) {
    const errorMessage = `エラーが発生しました: ${error.message}`;
    console.error("API呼び出しエラー:", error);
    return errorMessage;
  }
}

function speakText(text) {
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = languageSelect.value;
  speechSynthesis.speak(utterance);
}

// JSONエクスポート機能
const exportJsonBtn = document.querySelector("#export-json-btn");

exportJsonBtn.onclick = () => {
  const messages = Array.from(chatContainer.children).map((node) => {
    return {
      role: node.classList.contains("user") ? "user" : "assistant",
      content: node.textContent,
    };
  });
  const blob = new Blob([JSON.stringify(messages, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "chat_history.json";
  a.click();
  URL.revokeObjectURL(url);
};

// ログアウト機能
const logoutBtn = document.querySelector("#logout-btn");

logoutBtn.onclick = () => {
  if (confirm('ログアウトしますか？チャット履歴も削除されます。')) {
    // 音声認識を停止
    if (isRecognizing) {
      isManuallyStopped = true;
      toggle_recog(false);
    }

    // すべてのデータをクリア
    localStorage.removeItem("chatHistory");
    localStorage.removeItem("sessionId");
    localStorage.removeItem("user_id");

    // ページをリロードして初期状態に戻す
    window.location.reload();
  }
};

async function checkUserName(userId) {
  try {
    const response = await fetch(`${ENDPOINT_HOST_URL}/check_user_name?user_id=${userId}`);
    const data = await response.json();
    return data;
  } catch (error) {
    console.error("ユーザー名チェックエラー:", error);
    return { exists: false };
  }
}

async function registerUserName(userId, userName) {
  try {
    const response = await fetch(`${ENDPOINT_HOST_URL}/register_user_name`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: userId,
        user_name: userName,
      }),
    });
    const data = await response.json();
    return data;
  } catch (error) {
    console.error("ユーザー名登録エラー:", error);
    return { error: "登録に失敗しました" };
  }
}

function updateUserIdDisplay() {
  userIdDisplay.textContent = `user_id: ${user_id}`;
}

async function initializeApp() {
  const saved = localStorage.getItem("chatHistory");
  if (saved) {
    const history = JSON.parse(saved);
    history.forEach(({ role, content }) => appendMessage(content, role));
  }

  if (localStorage.getItem("sessionId")) {
    currentSessionId = localStorage.getItem("sessionId");
  } else {
    currentSessionId = "audio_session_" + Date.now();
    localStorage.setItem("sessionId", currentSessionId);
  }

  if (localStorage.getItem("user_id")) {
    user_id = localStorage.getItem("user_id");
  } else {
    user_id = Math.floor(Math.random() * 1000000);
    localStorage.setItem("user_id", user_id);
  }

  updateUserIdDisplay();

  const userCheck = await checkUserName(user_id);

  if (!userCheck.exists) {
    const modal = new bootstrap.Modal(document.getElementById('userRegistrationModal'));
    modal.show();

    document.getElementById('registerBtn').addEventListener('click', async () => {
      const userName = document.getElementById('userName').value.trim();
      const nameError = document.getElementById('nameError');

      if (!userName) {
        nameError.textContent = 'お名前を入力してください';
        nameError.classList.remove('d-none');
        return;
      }

      nameError.classList.add('d-none');

      const result = await registerUserName(user_id, userName);

      if (result.error) {
        nameError.textContent = '登録に失敗しました。もう一度お試しください。';
        nameError.classList.remove('d-none');
      } else if (!result.success) {
        nameError.textContent = '登録に失敗しました。もう一度お試しください。';
        nameError.classList.remove('d-none');
      } else {
        modal.hide();
      }
    });

    document.getElementById('userName').addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        document.getElementById('registerBtn').click();
      }
    });
  }
}

window.onload = initializeApp;

document.addEventListener("click", () => {
  const utterThis = new SpeechSynthesisUtterance();

  utterThis.text = "";
  speechSynthesis.speak(utterThis);
});
