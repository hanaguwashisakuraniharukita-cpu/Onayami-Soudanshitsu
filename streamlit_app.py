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
    client = genai.Client(api_key=api_key.strip())

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("What is up?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Gemini 形式のコンテンツ作成
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in st.session_state.messages
        ]

        # 最新の 3.8-flash を明示的に指定
        # （プレフィックス付き 'models/gemini-3.8-flash' で指定します）
        try:
            response_stream = client.models.generate_content_stream(
                model="models/gemini-3.8-flash",
                contents=contents,
            )

            def stream_generator():
                try:
                    for chunk in response_stream:
                        if chunk.text:
                            yield chunk.text
                except errors.ServerError:
                    yield "\n\n*(Google サーバー側で一時的な接続混雑が発生しました。もう一度メッセージを送信してください)*"
                except errors.APIError as e:
                    yield f"\n\n*(APIエラー: {e.message})*"

            with st.chat_message("assistant"):
                full_response = st.write_stream(stream_generator())
            st.session_state.messages.append({"role": "assistant", "content": full_response})

        except errors.APIError as e:
            st.error(f"APIエラーが発生しました: {e.message}")
        except Exception as e:
            st.error(f"エラー: {str(e)}")
