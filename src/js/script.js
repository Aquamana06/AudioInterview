const startBtn = document.querySelector("#start-btn");
const stopBtn = document.querySelector("#stop-btn");
const clearBtn = document.querySelector("#clear-btn");
const languageSelect = document.querySelector("#language-select");
const resultDiv = document.querySelector("#result-div");
const statusDiv = document.querySelector("#status-div");
const chatContainer = document.querySelector("#chat-container");
const navBar = document.querySelector("nav");
const ENDPOINT_HOST_URL = "https://resilience-interviewer.onrender.com"; // APIのホストURL
// Flag to track manual stop
let isManuallyStopped = false;

// セッションIDを固定
let currentSessionId = 'audio_session_' + Date.now();

// 音声認識のタイマー設定
let silenceTimer = null;
const SILENCE_TIMEOUT = 3000; // 3秒
let hasSpokenOnce = false; // ユーザーが一度でも話したかのフラグ

function resetSilenceTimer() {
    if (silenceTimer) {
        clearTimeout(silenceTimer);
    }
    silenceTimer = setTimeout(() => {
        console.log("3秒以上の沈黙を検出、音声認識を終了");
        recognition.stop();
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
    chatContainer.scrollTop = chatContainer.scrollHeight;
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
    statusDiv.textContent = "音声認識中...";
    navBar.classList.remove("waiting", "error");
    navBar.classList.add("recognizing");
    clearSilenceTimer(); // タイマーをクリア
};

recognition.onend = () => {
    statusDiv.textContent = "待機中";
    navBar.classList.remove("recognizing", "error");
    navBar.classList.add("waiting");
    clearSilenceTimer(); // タイマーをクリア
    if (!isManuallyStopped) {
        recognition.start(); // Auto-restart
    } else {
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }
};

recognition.onerror = (event) => {
    statusDiv.textContent = `エラー: ${event.error}`;
    navBar.classList.remove("recognizing", "waiting");
    navBar.classList.add("error");
    clearSilenceTimer(); // タイマーをクリア
    startBtn.disabled = false;
    stopBtn.disabled = true;
};

recognition.onresult = async (event) => {
    let interimTranscript = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
        let transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
            finalTranscript += transcript;
            
            // 空文字や空白のみの場合はスキップ
            if (transcript.trim().length > 0) {
                appendMessage(transcript, "user");
                clearSilenceTimer(); // 最終結果でタイマーをクリア

                const reply = await sendToInterviewer(finalTranscript);
                appendMessage(reply, "assistant");
                speakText(reply);
            }
        } else {
            interimTranscript = transcript;
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
    recognition.start();
    startBtn.disabled = true;
    stopBtn.disabled = false;
    
    // 初回開始時の挨拶メッセージ（履歴がない場合のみ）
    const saved = localStorage.getItem("chatHistory");
    if (!saved) {
        const initMessage = "本日はどのような思いや考えを持って日々の業務に取り組んでいるのかお聞かせいただけると幸いです。よろしくお願いします";
        appendMessage(initMessage, "assistant");
        speakText(initMessage);
    }
};

stopBtn.onclick = () => {
    isManuallyStopped = true;
    recognition.abort(); // 強制停止（onendが呼ばれなくなる）
    startBtn.disabled = false;
    stopBtn.disabled = true;
};

clearBtn.onclick = () => {
    finalTranscript = "";
    chatContainer.innerHTML = "";
    localStorage.removeItem("chatHistory");
    console.log("履歴をクリアしました");
};

async function sendToInterviewer(promptText) {
    console.log("受信テキスト:", promptText);
    
    try {
        const response = await fetch(`${ENDPOINT_HOST_URL}/audio_interview`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                text: promptText,
                session_id: currentSessionId // 固定のセッションIDを使用
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        const response_text = data.response;
        console.log("応答:", response_text);
        return response_text;
        
    } catch (error) {
        console.error("API呼び出しエラー:", error);
        return "申し訳ございません。エラーが発生しました。";
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

// 履歴の復元: ローカルストレージから
window.onload = () => {
    const saved = localStorage.getItem("chatHistory");
    if (saved) {
        const history = JSON.parse(saved);
        history.forEach(({ role, content }) => appendMessage(content, role));
    }
};

document.addEventListener('click', () => {
    const utterThis = new SpeechSynthesisUtterance();
  
    utterThis.text = '';
    speechSynthesis.speak(utterThis);
  });