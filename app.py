# Importing required packages
import streamlit as st
import openai
import uuid
import time
import pandas as pd
import io
from openai import OpenAI
import tiktoken

# Function to calculate message cost
def calculate_message_cost(message: str, encoding_name: str, price_per_1k_tokens: float):
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(message))
    cost = (num_tokens / 1000) * price_per_1k_tokens
    return num_tokens, cost

# Initialize OpenAI client
client = OpenAI()

# Choose between two assistants from the sidebar
assistant_choice = st.sidebar.selectbox(
    "Choose your Assistant",
    ("Assistant 1", "Assistant 2"),
    index=0  # Default to the first assistant
)

# Adjust MODEL, pricing, and assistant ID based on the assistant chosen
if assistant_choice == "Assistant 1":
    MODEL = "gpt-4-0125-preview"  # Latest model
    price_per_1k_tokens_user = 0.01
    price_per_1k_tokens_assistant = 0.03
    assistant_key = st.secrets["ASSISTANT_1_KEY"]  # Retrieve Assistant 1 key
else:
    MODEL = "gpt-4-1106-preview"  # Alternative model with lower cost
    price_per_1k_tokens_user = 0.01 / 20  # One twentieth of the first one for the user
    price_per_1k_tokens_assistant = (0.03 / 20)  # One twentieth of the first one for the assistant's messages
    assistant_key = st.secrets["ASSISTANT_2_KEY"]  # Retrieve Assistant 2 key

# Initialize OpenAI assistant with the selected key
openai.api_key = st.secrets["OPENAI_API_KEY"]
st.session_state.assistant = openai.beta.assistants.retrieve(assistant_key)


# Initialize session state variables
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "run" not in st.session_state:
    st.session_state.run = {"status": None}

if "messages" not in st.session_state:
    st.session_state.messages = []

if "retry_error" not in st.session_state:
    st.session_state.retry_error = 0

# Set up the page
st.set_page_config(page_title="Grammar Assistant with Cost Calculator")
st.sidebar.title("Grammar Assistant")
st.sidebar.divider()
st.sidebar.markdown("Your name", unsafe_allow_html=True)
st.sidebar.markdown("Grammar bot")
st.sidebar.divider()


# Add a numeric input in the sidebar for the currency conversion multiplier
currency_multiplier = st.sidebar.number_input("Enter currency conversion multiplier", value=1.0, format="%.4f")
currency_name = st.sidebar.text_input("Enter your currency name", value="Your Currency")


# File uploader for CSV, XLS, XLSX
uploaded_file = st.file_uploader("Upload your file", type=["csv", "xls", "xlsx"])

if uploaded_file is not None:
    # Determine the file type
    file_type = uploaded_file.type

    try:
        # Read the file into a Pandas DataFrame
        if file_type == "text/csv":
            df = pd.read_csv(uploaded_file)
        elif file_type in ["application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]:
            df = pd.read_excel(uploaded_file)

        # Convert DataFrame to JSON
        json_str = df.to_json(orient='records', indent=4)
        file_stream = io.BytesIO(json_str.encode())

        # Upload JSON data to OpenAI and store the file ID
        file_response = client.files.create(file=file_stream, purpose='answers')
        st.session_state.file_id = file_response.id
        st.success("File uploaded successfully to OpenAI!")

        # Optional: Display and Download JSON
        st.text_area("JSON Output", json_str, height=300)
        st.download_button(label="Download JSON", data=json_str, file_name="converted.json", mime="application/json")
    
    except Exception as e:
        st.error(f"An error occurred: {e}")

# Initialize OpenAI assistant
if "assistant" not in st.session_state:
    openai.api_key = st.secrets["OPENAI_API_KEY"]
    st.session_state.assistant = openai.beta.assistants.retrieve(st.secrets["OPENAI_ASSISTANT"])
    st.session_state.thread = client.beta.threads.create(
        metadata={'session_id': st.session_state.session_id}
    )

# Display chat messages with token count, cost information, and converted cost
elif hasattr(st.session_state.run, 'status') and st.session_state.run.status == "completed":
    st.session_state.messages = client.beta.threads.messages.list(
        thread_id=st.session_state.thread.id
    )
    for message in reversed(st.session_state.messages.data):
        if message.role in ["user", "assistant"]:
            with st.chat_message(message.role):
                for content_part in message.content:
                    message_text = content_part.text.value
                    st.markdown(f"""<div dir="rtl"> {message_text}</div>""", unsafe_allow_html=True)
                    
                    # Determine pricing based on the role
                    if message.role == "user":
                        price_per_1k_tokens = 0.01
                    else:  # For assistant's messages, the cost is three times higher
                        price_per_1k_tokens = 0.03
                    
                    # Calculate tokens and cost
                    num_tokens, message_cost = calculate_message_cost(message_text, "cl100k_base", price_per_1k_tokens)
                    
                    # Convert cost to user's currency
                    cost_in_user_currency = message_cost * currency_multiplier
                    
                    # Display token count, cost info, and converted cost
                    cost_info = f"Tokens: {num_tokens}, Estimated Cost: ${message_cost:.4f}, {currency_name}: {cost_in_user_currency:.4f}"
                    st.caption(cost_info)


# Chat input and message creation with file ID
if prompt := st.chat_input("How can I help you?"):
    with st.chat_message('user'):
        st.write(prompt)

    message_data = {
        "thread_id": st.session_state.thread.id,
        "role": "user",
        "content": prompt
    }

    # Include file ID in the request if available
    if "file_id" in st.session_state:
        message_data["file_ids"] = [st.session_state.file_id]

    st.session_state.messages = client.beta.threads.messages.create(**message_data)

    st.session_state.run = client.beta.threads.runs.create(
        thread_id=st.session_state.thread.id,
        assistant_id=st.session_state.assistant.id,
    )
    if st.session_state.retry_error < 3:
        time.sleep(1)
        st.rerun()

# Handle run status
if hasattr(st.session_state.run, 'status'):
    if st.session_state.run.status == "running":
        with st.chat_message('assistant'):
            st.write("Thinking ......")
        if st.session_state.retry_error < 3:
            time.sleep(1)
            st.rerun()

    elif st.session_state.run.status == "failed":
        st.session_state.retry_error += 1
        with st.chat_message('assistant'):
            if st.session_state.retry_error < 3:
                st.write("Run failed, retrying ......")
                time.sleep(3)
                st.rerun()
            else:
                st.error("FAILED: The OpenAI API is currently processing too many requests. Please try again later ......")

    elif st.session_state.run.status != "completed":
        st.session_state.run = client.beta.threads.runs.retrieve(
            thread_id=st.session_state.thread.id,
            run_id=st.session_state.run.id,
        )
        if st.session_state.retry_error < 3:
            time.sleep(3)
            st.rerun()
