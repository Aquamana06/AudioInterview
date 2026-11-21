"""Chemical-plant vocabulary supplied to Whisper as transcription context.

Keep this list short and domain-specific. It is a hint to the recognizer, not
an instruction to blindly rewrite every occurrence.
"""

DOMAIN_TERMS = (
    "計器", "圧力計", "温度計", "流量計", "回収", "廃液", "棟", "銘柄","メタノール", "樹脂", "ポバール", "界面活性剤",  
     "弁", "熱交換器", "蒸留塔", "反応槽", "配管","M元タンク", "未鹸化物", "NM","12棟", "5棟","X列", "N列",
    "インターロック", "DCS", "鹸化", "重合", "重合塔",
    "点検", "発泡", "五感","異音","異臭",
)

# Whisper uses preceding transcript context, rather than following chat-style
# instructions. Supply correct spellings only; incorrect examples can bias it.
TRANSCRIPTION_PROMPT = (
    "化学プラントのオペレータについてのインタビューです。"
    "登場する専門用語：" + "、".join(DOMAIN_TERMS) + "。"
)
