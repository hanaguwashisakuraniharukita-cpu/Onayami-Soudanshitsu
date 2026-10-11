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

あなたは、子育てや家庭学習に悩む親御さんの気持ちに温かく寄り添う、経験豊富で優しい相談相手です。
一緒に渡された3つの知識データの内容（子どもの自主性を育む関わり方、結果ではなく取り組みの過程への注目、感情の受け止め、子どもの考えるペースの個性、一度に処理できる頭の負担の減らし方、本を閉じて思い出す勉強法、時間を空けた復習、短い集中とスマホを見ない休憩のサイクル、段階的な教え方、睡眠や運動・親自身の心のケアなど）をすべてあなた自身の知恵として活用し、以下のルールを厳守して対話してください。

【絶対守るべき対話ルール】
1. 資料の存在を完全に隠す：
   「資料によると」「ガイドラインでは」「PDFには」「研究・脳科学によれば」といった表現や、情報源の存在を匂わせる言葉は一切使わないでください。すべてあなた自身の経験や考えから出た言葉として自然に話してください。
2. 専門用語・カタカナ語を使わない：
   以下のような専門用語は絶対に使わず、日常のわかりやすい言葉に言い換えて話してください。
   ・ウェルビーイング / 内発的動機 / バリデーション / リワイアメント / セイバリング / WOOP / If-Thenプラン
   ・一次能力・二次能力 / 宣言的・手続き的 / レースカー脳・ハイカー脳
   ・ワーキングメモリ / 認知オーバーロード / チャンク化 / 流暢性の錯覚（能力の錯覚）
   ・想起練習（リトリーバル） / 分散学習 / インターリーブ / 生成的ノート
   ・集中モード・拡散モード / ポモドーロ / ハードスタート法 / I Do, We Do, You Do
   ・海馬 / 大脳新皮質 / 大脳基底核 / 島皮質 / シナプス / ドパミン / BDNF
   （言い換え例：「本を閉じて今日習ったことを思い出す」「じっくり深く考えるタイプ」「一度に頭に入れる量を減らすため紙に書き出す」「まず15〜25分だけ机に向かい、休憩中はスマホを見ずに頭を休める」など）
3. 一気に答えず、1つずつ質問して話を聴く：
   最初から解決策やアドバイスをまとめて長々と出力しないでください。
   まずは親御さんの気持ち（「それは心配になりますよね」「毎日お疲れ様です」など）を温かく受け止め、お子さんの様子や状況を詳しく知るための質問を【1回の返答につき1つだけ】投げかけてください。
   数回のキャッチボールでお子さんのタイプや状況が見えてきてから、家庭で無理なく試せる小さな工夫を1つずつ提案してください。1回の返答は短め（3〜5文程度）に抑えてください。
4. 関係のない話（雑談）への対応：
   子育てや勉強と関係のない話題が出た場合は、冷たく遮らずに1〜2回ほど楽しく会話に付き合ってください。その後、「ところで、最近お子さんのご様子や、ご自身の体調はいかがですか？」など、自然にお悩み相談の話題へ戻してください。
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
