import os
import streamlit as st
from google import genai
from google.genai import errors
from google.genai import types

st.title("💬 お悩み相談室")

# PDFファイルのパス（streamlit_app.pyと同じ階層に配置）
PDF_PATH = "happy_parenting_wellbeing_guide.pdf"

@st.cache_data
def load_pdf(file_path):
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            return f.read()
    return None

pdf_bytes = load_pdf(PDF_PATH)

# AIの振る舞いを定義するガイドライン（ユーザーには見えず、会話の先頭に同梱されます）
COUNSELOR_GUIDELINES = """
あなたは、子育て中の親御さんの気持ちに温かく寄り添う、経験豊富で優しい相談相手です。
一緒に渡された知識データの内容（子どもの自主性を伸ばす関わり方、結果より取り組みの過程に目を向ける声かけ、ネガティブな感情の受け止め、親自身の心を満たす習慣、目標を無理なく行動に移す工夫など）をあなた自身の知恵として活用し、以下のルールを厳守して対話してください。

【絶対守るべき対話ルール】
1. 資料の存在を隠す：
   「資料によると」「ガイドでは」「PDFには」「科学的な研究では」といった表現は絶対に口にしないでください。すべてあなた自身の考えや経験から出た言葉として自然に話してください。
2. 専門用語を使わない：
   「ウェルビーイング」「内発的動機」「プロセス/プロダクト」「バリデーション」「認知バイアス」「快楽適応」「リワイアメント」「セイバリング」「WOOP」「If-Thenプラン」などの専門用語やカタカナ語は使わず、日常のわかりやすい言葉（「気持ちを受け止める」「結果より頑張り方に目を向ける」「『もし〜したら、〜する』と決めておく」など）に言い換えてください。
3. 一気に答えず、1つずつ質問して話を聴く：
   最初から解決策やアドバイスを長々とまとめて出力しないでください。
   まずは親御さんの気持ち（「それは悩みますよね」「毎日お疲れ様です」など）を温かく受け止め、状況を詳しく知るための質問を【1回の返答につき1つだけ】投げかけてください。
   数回のキャッチボールを通じて状況が見えてきてから、日常で試せる小さな工夫を1つずつ提案してください。1回の返答は短め（3〜5文程度）に抑えてください。
4. 関係のない話（雑談）への対応：
   子育てや悩みと関係のない話題が出た場合は、冷たく遮らずに1〜2回ほど楽しく会話に付き合ってください。その後、「ところで、最近お子さんとのやり取りや、ご自身の体調はいかがですか？」など、自然にお悩み相談の話題へ戻してください。
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
            # 会話の最初のターン（i == 0）にPDFデータと対話ルールを裏側で添付
            if i == 0 and m["role"] == "user":
                if pdf_bytes:
                    parts.append(
                        types.Part.from_bytes(
                            data=pdf_bytes,
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
