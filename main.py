from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import diff_match_patch as dmp_module
from llama_cpp import Llama
import re
import threading
import queue
import uuid
#TODO: Currently, when the text is written by multiple clients, the draw and update function is
# probably called concurrently. This causes problems with both retrieving the text for creating a patch
# and receiving inputs!!!
# NO! The problem is probably in variable isLocalChange
# Currently, the events cannot be processed concurrently
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='threading')

# Initialize the language model
llm = Llama(
    model_path="gemma-2-2b-it-IQ4_XS.gguf",
    verbose=False,
    n_threads=8,
    n_ctx=8128,  # Set the max context to 256 tokens
    n_batch=1024,
    n_gpu_layers=1000
)

# Store the markdown content
shared_content = {"markdown": ""}
dmp = dmp_module.diff_match_patch()

# Task queue to process LLM tasks one-by-one
llm_task_queue = queue.Queue()
lock = threading.Lock()

# Base prompt for LLM
turn_system = "<start_of_turn>user\n"
turn_user = "<end_of_turn>\n<start_of_turn>user\n"
turn_assistant = "<end_of_turn>\n<start_of_turn>model\n"
prompt_base = f"{turn_system}You help to write conspect. You can use tables, blockquotes, lists, formulas (in the following format: $<math>$), code, and other formatting. Be concise, answer as shortly as possible, use formatting where possible. When answering, proceed to request, avoid writing anything before and after answer."


def truncate_context(context, prompt, max_context_length=512, before_ratio=0.8, after_ratio=0.2):
    tokens = llm.tokenize(context.encode("utf-8"))
    prompt_tokens = llm.tokenize(prompt.encode("utf-8"))
    if len(tokens) + len(prompt_tokens) <= max_context_length:
        return context  # No need to truncate

    prompt_index = context.find(prompt)
    if prompt_index == -1:
        return context  # Prompt not found, returning full context

    before_prompt = int(max_context_length * before_ratio)
    after_prompt = max_context_length - before_prompt

    prompt_start_token = len(llm.tokenize(context[:prompt_index].encode("utf-8")))
    start_idx = max(0, prompt_start_token - before_prompt)
    end_idx = min(len(tokens), prompt_start_token + len(prompt_tokens) + after_prompt)

    truncated_tokens = tokens[start_idx:end_idx]
    truncated_context = llm.detokenize(truncated_tokens)
    return truncated_context


def process_llm_task(unique_id, user_text):
    with lock:
        current_markdown = shared_content['markdown']
    prompt = f"\n\nUser request regarding the text:\n{user_text}{turn_assistant}"

    # Truncate context
    truncated_context = truncate_context(current_markdown, f"=\\{user_text}\\", max_context_length=1024)
    full_prompt = f"{prompt_base}\n...{truncated_context}...{prompt}"

    # Placeholder for AI generation
    placeholder = f"=> {unique_id}\n"

    with lock:
        updated_markdown = shared_content['markdown'].replace(f'=\\{user_text}\\=', placeholder, 1)
        shared_content['markdown'] = updated_markdown

        # Send patch update to the clients
        diffs = dmp.diff_main(current_markdown, updated_markdown)
        if diffs:
            dmp.diff_cleanupSemantic(diffs)
            patches = dmp.patch_make(current_markdown, updated_markdown)
            patch_text = dmp.patch_toText(patches)
            socketio.emit('patch_update', {'patchText': patch_text, 'senderId': 'llm'}, to=None)
            socketio.sleep(0)

    # Generate text using the language model
    full_str = ""
    for output in llm(full_prompt, max_tokens=2048, stop=["<|end|>", "<end_of_turn>"], stream=True):
        token_str = output["choices"][0]["text"]
        # print(token_str, end="", flush=True)
        with (lock):

            current_markdown = shared_content['markdown']

            if len(full_str)<=0:
                if (placeholder + full_str not in current_markdown):
                    # print("BREAK!")
                    return
                updated_markdown = current_markdown.replace(placeholder + full_str,
                                                        placeholder + full_str + token_str + "<=|", 1)
            else:
                if (placeholder + full_str + "<=|" not in current_markdown):
                    # print("BREAK!")
                    return
                updated_markdown = current_markdown.replace(placeholder + full_str + "<=|",
                                                        placeholder + full_str + token_str + "<=|", 1)

            # print(current_markdown, updated_markdown)
            shared_content['markdown'] = updated_markdown
        # Send real-time updates to clients
        full_str += token_str
        # print(full_str)
        diffs = dmp.diff_main(current_markdown, updated_markdown)
        if diffs:
            dmp.diff_cleanupSemantic(diffs)
            patches = dmp.patch_make(current_markdown, updated_markdown)
            patch_text = dmp.patch_toText(patches)
            socketio.emit('patch_update', {'patchText': patch_text, 'senderId': 'llm'}, to=None)
            socketio.sleep(0)


    # Replace the placeholder once generation is complete
    with lock:
        current_markdown = shared_content['markdown']
        updated_markdown = current_markdown.replace(placeholder + full_str + "<=|", full_str, 1)

        diffs = dmp.diff_main(current_markdown, updated_markdown)
        if diffs:
            dmp.diff_cleanupSemantic(diffs)
            patches = dmp.patch_make(current_markdown, updated_markdown)
            patch_text = dmp.patch_toText(patches)
            socketio.emit('patch_update', {'patchText': patch_text, 'senderId': 'llm'}, to=None)
            socketio.sleep(0)

        shared_content['markdown'] = updated_markdown



def llm_worker():
    while True:
        unique_id, user_text = llm_task_queue.get()
        process_llm_task(unique_id, user_text)
        llm_task_queue.task_done()


# Start the LLM background worker thread
llm_thread = threading.Thread(target=llm_worker, daemon=True)
llm_thread.start()


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    with lock:
        diffs = dmp.diff_main("", shared_content['markdown'])
    patches = dmp.patch_make("", diffs)
    emit('patch_update', {'patchText': dmp.patch_toText(patches), 'senderId': None})
    socketio.sleep(0)


@socketio.on('markdown_patch')
def handle_markdown_patch(data):
    print(data)
    patch_text = data['patchText']
    sender_id = data['clientId']

    patches = dmp.patch_fromText(patch_text)
    with lock:
        new_markdown, _ = dmp.patch_apply(patches, shared_content['markdown'])
        shared_content['markdown'] = new_markdown

    emit('patch_update', {'patchText': patch_text, 'senderId': sender_id}, broadcast=True)
    socketio.sleep(0)


@socketio.on('process_special_format')
def handle_process_special_format(data):
    special_lines = data['matches']

    # Assign a unique ID to each LLM task
    for line in special_lines:
        unique_id = str(uuid.uuid4())
        llm_task_queue.put((unique_id, line))


if __name__ == '__main__':
    socketio.run(app, debug=True, host="0.0.0.0", allow_unsafe_werkzeug=True)
