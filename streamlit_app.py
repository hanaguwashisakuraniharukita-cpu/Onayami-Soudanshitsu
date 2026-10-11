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

# サイドバー設定
with st.sidebar:
    st.header("設定")
    selected_model = st.selectbox(
        "モデル選択",
        ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro"],
        index=0,
    )
    use_streaming = st.checkbox("ストリーミング表示を有効にする", value=True)
    
    # PDFの読み込み状態を表示
    if pdf_bytes:
        st.success(f"📚 知識データ読込済: {PDF_PATH}")
    else:
        st.warning(f"⚠️ {PDF_PATH} が見つかりません。GitHubにアップロードしてください。")

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
            # 会話の最初のターン（i == 0）にPDFファイルと参照の前提をパーツとして添付
            if i == 0 and m["role"] == "user" and pdf_bytes:
                parts.append(
                    types.Part.from_bytes(
                        data=pdf_bytes,
                        mime_type="application/pdf",
                    )
                )
                parts.append(
                    types.Part.from_text(
                        text="添付されたPDF資料の科学的エビデンスやフレームワークを知識として活用し、相談に回答してください。"
                    )
                )

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
