import streamlit as st

from langgraph_tool_backend import chatbot, retrieve_all_threads, get_thread_title

from langchain_core.messages import HumanMessage, AIMessage

import uuid

if 'app_initialized' not in st.session_state:
    all_threads = retrieve_all_threads()
    st.session_state['chat_threads'] = all_threads
    st.session_state['thread_titles'] = {t: get_thread_title(t) for t in all_threads}
    st.session_state['app_initialized'] = True
 
# **************************************** utility functions *************************
 
def generate_thread_id():

    return uuid.uuid4()
 
def load_conversation(thread_id):

    state = chatbot.get_state(config={'configurable': {'thread_id': thread_id}})

    # Check if messages key exists in state values, return empty list if not

    return state.values.get('messages', [])
 
 
# **************************************** Session Setup ******************************
 
if 'message_history' not in st.session_state:

    st.session_state['message_history'] = []
 
if 'thread_id' not in st.session_state:

    st.session_state['thread_id'] = None  # no active thread at first
 
if 'chat_threads' not in st.session_state:

    # List of thread_ids that already have at least one message

    st.session_state['chat_threads'] = []
 
if 'thread_titles' not in st.session_state:

    # Mapping: thread_id -> title (first user query)

    st.session_state['thread_titles'] = {}
 
if 'pending_new_chat' not in st.session_state:

    # True means next message starts a brand-new conversation

    st.session_state['pending_new_chat'] = True
 
 
# **************************************** MAIN INPUT (handled BEFORE sidebar) *******
 
# Chat input – we capture this early so we can create/rename the conversation

user_input = st.chat_input('Type here')
 
# If user sends a message that should start a new conversation:

if user_input and (st.session_state['pending_new_chat'] or st.session_state['thread_id'] is None):

    new_thread_id = generate_thread_id()

    st.session_state['thread_id'] = new_thread_id

    st.session_state['pending_new_chat'] = False
 
    # Add to list of conversations (will appear immediately in sidebar)

    if new_thread_id not in st.session_state['chat_threads']:

        st.session_state['chat_threads'].append(new_thread_id)
 
    # Use first user query as title (truncate if long)

    short_title = user_input.strip()

    if len(short_title) > 40:

        short_title = short_title[:37] + "..."

    st.session_state['thread_titles'][new_thread_id] = short_title
 
 
# **************************************** Sidebar UI *********************************
 
st.sidebar.title('LangGraph Chatbot')
 
# New Chat just prepares for a new thread; conversation appears after first query

if st.sidebar.button('New Chat'):

    st.session_state['message_history'] = []

    st.session_state['thread_id'] = None

    st.session_state['pending_new_chat'] = True
 
st.sidebar.header('My Conversations')
 
# Show latest conversations first

for thread_id in st.session_state['chat_threads'][::-1]:

    title = st.session_state['thread_titles'].get(thread_id, str(thread_id))
 
    if st.sidebar.button(title, key=f"thread-btn-{thread_id}"):

        # Switch to that thread

        st.session_state['thread_id'] = thread_id

        st.session_state['pending_new_chat'] = False
 
        messages = load_conversation(thread_id)

        temp_messages = []

        for msg in messages:

            if isinstance(msg, HumanMessage):

                role = 'user'

            else:

                role = 'assistant'

            temp_messages.append({'role': role, 'content': msg.content})
 
        st.session_state['message_history'] = temp_messages
 
 
# **************************************** Main UI ************************************
 
# Show current conversation history

for message in st.session_state['message_history']:

    with st.chat_message(message['role']):

        st.text(message['content'])
 
# Handle the message content (both for new and existing threads)

if user_input:

    current_thread = st.session_state['thread_id']
 
    # Append user message

    st.session_state['message_history'].append({'role': 'user', 'content': user_input})

    with st.chat_message('user'):

        st.text(user_input)
 
    CONFIG = {'configurable': {'thread_id': current_thread}}
 
    # Get AI response

    with st.chat_message("assistant"):

        def ai_only_stream():

            for message_chunk, metadata in chatbot.stream(

                {"messages": [HumanMessage(content=user_input)]},

                config=CONFIG,

                stream_mode="messages"

            ):

                if isinstance(message_chunk, AIMessage):

                    yield message_chunk.content
 
        ai_message = st.write_stream(ai_only_stream())
 
    st.session_state['message_history'].append({'role': 'assistant', 'content': ai_message})
 