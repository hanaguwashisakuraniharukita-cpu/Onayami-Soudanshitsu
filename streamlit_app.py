import streamlit as st
from google import genai
from google.genai import types

# Show title and description.
st.title("💬 Chatbot")
st.write(
    "This is a simple chatbot that uses Google's Gemini model to generate responses. "
    "To use this app, you need to provide a Gemini API key, which you can get [here](https://aistudio.google.com/app/apikey). "
    "You can also store the API key in `.streamlit/secrets.toml`."
)

# Ask user for their Gemini API key via `st.text_input`.
# Alternatively, check for an API key stored in `.streamlit/secrets.toml`
api_key = st.secrets.get("GEMINI_API_KEY") if "GEMINI_API_KEY" in st.secrets else None

if not api_key:
    api_key = st.text_input("Gemini API Key", type="password")

if not api_key:
    st.info("Please add your Gemini API key to continue.", icon="🗝️")
else:
    # Create a Gemini client.
    client = genai.Client(api_key=api_key)

    # Create a session state variable to store the chat messages.
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display the existing chat messages via `st.chat_message`.
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Create a chat input field.
    if prompt := st.chat_input("What is up?"):
        # Store and display the current prompt.
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Convert chat history to Gemini's Content format.
        # Note: Gemini requires the assistant role to be named 'model'.
        contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in st.session_state.messages
        ]

        # Generate a streaming response.
        response_stream = client.models.generate_content_stream(
            model="gemini-2.5-flash",
            contents=contents,
        )

        # Helper generator to yield text chunks to st.write_stream.
        def stream_generator():
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text

        # Stream the response to the chat, then store it in session state.
        with st.chat_message("assistant"):
            full_response = st.write_stream(stream_generator())
        st.session_state.messages.append({"role": "assistant", "content": full_response})
