import streamlit as st
from google import genai
from google.genai import errors
from google.genai import types

# Show title and description.
st.title("💬 Chatbot")
st.write(
    "This is a simple chatbot that uses Google's Gemini model to generate responses. "
    "To use this app, you need to provide a Gemini API key, which you can get [here](https://aistudio.google.com/app/apikey). "
    "You can also store the API key in `.streamlit/secrets.toml`."
)

# APIキーの取得
api_key = st.secrets.get("GEMINI_API_KEY") if "GEMINI_API_KEY" in st.secrets else None

if not api_key:
    api_key = st.text_input("Gemini API Key", type="password")

if not api_key:
    st.info("Please add your Gemini API key to continue.", icon="🗝️")
else:
    # 前後の不要な空白を除去してクライアント作成
    client = genai.Client(api_key=api_key.strip())

    # 会話履歴の初期化
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 過去ログの表示
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # ユーザー入力
    if prompt := st.chat_input("What is up?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Gemini 向けに履歴フォーマットを変換
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in st.session_state.messages
        ]

        try:
            # 正式なモデル名 'gemini-2.5-flash' を指定
            response_stream = client.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=contents,
            )

            def stream_generator():
                try:
                    for chunk in response_stream:
                        if chunk.text:
                            yield chunk.text
                except errors.APIError as stream_err:
                    yield f"\n\n**APIエラーが発生しました:** {stream_err.message}"

            with st.chat_message("assistant"):
                full_response = st.write_stream(stream_generator())
            st.session_state.messages.append({"role": "assistant", "content": full_response})

        except errors.APIError as e:
            st.error(f"Gemini API エラー ({e.code}): {e.message}")
        except Exception as e:
            st.error(f"予期しないエラー: {str(e)}")
