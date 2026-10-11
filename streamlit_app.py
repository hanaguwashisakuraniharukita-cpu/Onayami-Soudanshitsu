import streamlit as st
from google import genai
from google.genai import errors
from google.genai import types

st.title("💬 Chatbot")

# サイドバー設定
with st.sidebar:
    st.header("設定")
    selected_model = st.selectbox(
        "モデル選択",
        ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro"],
        index=0,
    )
    use_streaming = st.checkbox("ストリーミング表示を有効にする", value=True)
    if st.button("🗑️ 会話履歴をクリア"):
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
    if prompt := st.chat_input("What is up?"):
        # 画面表示と履歴保存
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 履歴データの生成（正常な発言のみ）
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in st.session_state.messages
        ]

        full_response = ""
        success = False

        try:
            with st.chat_message("assistant"):
                if use_streaming:
                    # ストリーミング実行
                    response_stream = client.models.generate_content_stream(
                        model=selected_model,
                        contents=contents,
                    )

                    def stream_generator():
                        for chunk in response_stream:
                            if chunk.text:
                                yield chunk.text

                    full_response = st.write_stream(stream_generator())
                else:
                    # 通常生成（ストリーミング不調時の切り分け用）
                    with st.spinner("生成中..."):
                        response = client.models.generate_content(
                            model=selected_model,
                            contents=contents,
                        )
                        full_response = response.text
                        st.markdown(full_response)

                success = True

        except errors.APIError as e:
            st.error(f"**Gemini API Error [{e.code}]**: {e.message}")
        except Exception as e:
            st.error(f"**Error**: {type(e).__name__} - {str(e)}")

        # 成功した時のみ履歴に追加（エラー文は履歴に保存しない）
        if success and full_response:
            st.session_state.messages.append({"role": "assistant", "content": full_response})
        else:
            # 失敗した場合は直前のユーザー入力も履歴から削除してロールバック
            st.session_state.messages.pop()
