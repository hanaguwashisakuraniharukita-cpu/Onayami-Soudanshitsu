import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from google import genai
from google.genai import errors
from google.genai import types

# 1. 日本標準時（JST）へのタイムゾーン設定
os.environ["TZ"] = "Asia/Tokyo"
if hasattr(time, "tzset"):
    time.tzset()

JST = ZoneInfo("Asia/Tokyo")

st.title("💬 お悩み相談室")

# 2. 同列に配置する3つのPDFファイル
PDF_FILES = [
    "happy_parenting_wellbeing_guide.pdf",
    "parent_guide_brain_science_learning.pdf",
    "Learning how to learn.pdf",
]

@st.cache_data
def load_all_pdfs(file_list):
    loaded = []
    for file_path in file_list:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                loaded.append(f.read())
    return loaded

pdf_bytes_list = load_all_pdfs(PDF_FILES)

# 現在の日本日時を取得（曜日付き）
weekdays = ["月", "火", "水", "木", "金", "土", "日"]
now_jst = datetime.now(JST)
current_time_str = f"{now_jst.strftime('%Y年%m月%d日')}({weekdays[now_jst.weekday()]}) {now_jst.strftime('%H:%M')}"

# 3. AIの振る舞いを定義するガイドライン（system_instructionは使わず会話データ先頭に同梱）
COUNSELOR_GUIDELINES = f"""
現在の日本時間: {current_time_str}

あなたは、教育心理学・脳科学・幸福学の深い知見を持ち、子育てや家庭学習に悩む親御さんに温かく寄り添う経験豊富な専門家カウンセラーです。
一緒に渡された3つの知識データの内容をすべて「あなた自身の専門知識・経験」として完全に内面化し、以下のルールを厳守して対話してください。

【絶対守るべき対話ルール】
1. 資料の存在を完全に隠す：
   「資料によると」「ガイドラインでは」「PDFには」「添付データでは」といった情報源の存在を匂わせる表現は絶対に使わないでください。すべてあなた自身の知見として自然に語ってください。

2. 専門用語は「平易な解説・日常の比喩」と必ずセットで使う：
   専門家としての説得力を保つため、適切な場面では専門用語やフレームワーク名（例：ワーキングメモリ、認知オーバーロード、想起練習、分散学習、インターリーブ、流暢性の錯覚、集中モードと拡散モード、レースカー脳とハイカー脳、手続き的記憶と宣言的記憶、ポモドーロ・テクニック、チャンク化、島皮質、BDNF、バリデーション、快楽適応、セイバリング、WOOPモデル、If-Thenプランなど）を使用して構いません。
   ただし、用語を単体で投げっぱなしにせず、必ず直後に「小学生でもイメージできる日常の例えや平易な解説」を添えてください。
   ・良い例：「人間の頭の中には『ワーキングメモリ』という小さな作業机があるのですが、ここには一度に4つくらいの情報しか置けません。だから複雑な問題は紙に書き出して、机の上を空けてあげることが大切なんです」
   ・良い例：「教科書を何度も読むと、脳が覚えたと勘違いする『流暢性の錯覚（わかったつもり）』が起きやすいんです。本を閉じて自力で思い出す『想起練習』に切り替えると、記憶がグッと定着しますよ」
   ※1回の返答で使う専門用語は多くても1〜2個までに絞り、ペダンティック（知識のひけらかし）にならないようにしてください。

3. 一気に答えず、1つずつ質問して状況を聴く：
   最初から解決策や知識を長々とまとめて出力しないでください。
   まずは親御さんの気持ち（「それは気がかりですよね」「毎日本当にお疲れ様です」など）を温かく受け止め、お子さんの様子や状況を把握するための質問を【1回の返答につき1つだけ】投げかけてください。
   数回のキャッチボールでお子さんのタイプや状況が見えてきてから、上記の専門的視点と具体的なアクションを1つずつ簡潔に（3〜6文程度で）提案してください。

4. 関係のない話（雑談）への対応：
   子育てや学習と関係のない話題が出た場合は、冷たく遮らずに1〜2回ほど和やかに会話に付き合ってください。その後、「ところで、最近お子さんのご様子や、ご自身の体調はいかがですか？」など、自然にお悩み相談の話題へ戻してください。
"""

# サイドバー設定
with st.sidebar:
    st.header("設定")
    selected_model = st.selectbox(
        "モデル選択",
        ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro"],
        index=0,
    )
    use_streaming = st.checkbox("ストリーミング表示を有効にする", value=True)
    if st.button("🗑️ 会話履歴をクリアする"):
        st.session_state.messages = []
        st.rerun()

# APIキーの取得
api_key = st.secrets.get("GEMINI_API_KEY") if "GEMINI_API_KEY" in st.secrets else None
if not api_key:
    api_key = st.text_input("Gemini API Key", type="password")

if not api_key:
    st.info("APIキーを入力してください。", icon="🗝️")
else:
    client = genai.Client(api_key=api_key.strip())

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 過去ログ描画
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # ユーザー入力
    if prompt := st.chat_input("今日はどのようなご相談ですか"):
        # 画面表示と履歴保存
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 履歴データの生成
        contents = []
        for i, m in enumerate(st.session_state.messages):
            parts = []
            # 会話の最初のターン（i == 0）に3つのPDFデータと対話ルールを同梱
            if i == 0 and m["role"] == "user":
                for pdf_data in pdf_bytes_list:
                    parts.append(
                        types.Part.from_bytes(
                            data=pdf_data,
                            mime_type="application/pdf",
                        )
                    )
                parts.append(types.Part.from_text(text=COUNSELOR_GUIDELINES))

            parts.append(types.Part.from_text(text=m["content"]))

            contents.append(
                types.Content(
                    role="model" if m["role"] == "assistant" else "user",
                    parts=parts,
                )
            )

        full_response = ""
        success = False

        with st.chat_message("assistant"):
            thinking_placeholder = st.empty()
            thinking_placeholder.markdown("（・・・今考えています）")

            try:
                if use_streaming:
                    response_stream = client.models.generate_content_stream(
                        model=selected_model,
                        contents=contents,
                    )

                    def stream_generator():
                        for chunk in response_stream:
                            if chunk.text:
                                thinking_placeholder.empty()
                                yield chunk.text

                    full_response = st.write_stream(stream_generator())
                else:
                    response = client.models.generate_content(
                        model=selected_model,
                        contents=contents,
                    )
                    full_response = response.text
                    thinking_placeholder.markdown(full_response)

                success = True

            except errors.APIError as e:
                thinking_placeholder.empty()
                st.error(f"**Gemini API Error [{e.code}]**: {e.message}")
            except Exception as e:
                thinking_placeholder.empty()
                st.error(f"**Error**: {type(e).__name__} - {str(e)}")

        # 成功した時のみ履歴に追加
        if success and full_response:
            st.session_state.messages.append({"role": "assistant", "content": full_response})
        else:
            st.session_state.messages.pop()
