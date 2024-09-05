from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import diff_match_patch as dmp_module
from llama_cpp import Llama
import re

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

turn_system = "<start_of_turn>user\n"
turn_user = "<end_of_turn>\n<start_of_turn>user\n"
turn_assistant = "<end_of_turn>\n<start_of_turn>model\n"
prompt_base = f"{turn_system}You help to write conspect. You can use tables, blockquotes, lists, formulas (in the following format: $<math>$), code, and other formatting. Be concise, answer as shortly as possible, use formatting where possible. Answer without referencing user, just proceed to request"


def truncate_context(context, prompt, max_context_length=512, before_ratio=0.8, after_ratio=0.2):
    tokens = llm.tokenize(context.encode("utf-8"))
    prompt_tokens = llm.tokenize(prompt.encode("utf-8"))
    # if len(prompt_tokens)>2:
    #     prompt_tokens = prompt_tokens[1: -1]
    print(len(tokens) + len(prompt_tokens))
    if len(tokens) + len(prompt_tokens) <= max_context_length:
        print("fits")
        return context  # No need to truncate

    print("NEED TO TRUNCATE")
    prompt_index = context.find(prompt)
    print(context, prompt)
    print(prompt_index)
    if prompt_index == -1:
        print("CANNOT FIND PROMPT")
        return context  # Prompt not found, returning full context

    # Determine truncation range
    before_prompt = int(max_context_length * before_ratio)
    after_prompt = max_context_length - before_prompt

    prompt_start_token = len(llm.tokenize(context[:prompt_index].encode("utf-8")))
    start_idx = max(0, prompt_start_token - before_prompt)
    end_idx = min(len(tokens), prompt_start_token + len(prompt_tokens) + after_prompt)

    truncated_tokens = tokens[start_idx:end_idx]

    truncated_context = llm.detokenize(truncated_tokens)
    return truncated_context


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    diffs = dmp.diff_main("", shared_content['markdown'])
    patches = dmp.patch_make("", diffs)
    emit('patch_update', {'patchText': dmp.patch_toText(patches), 'senderId': None})


@socketio.on('markdown_patch')
def handle_markdown_patch(data):
    patch_text = data['patchText']
    sender_id = data['clientId']

    patches = dmp.patch_fromText(patch_text)
    new_markdown, _ = dmp.patch_apply(patches, shared_content['markdown'])
    shared_content['markdown'] = new_markdown

    emit('patch_update', {'patchText': patch_text, 'senderId': sender_id}, broadcast=True)


@socketio.on('process_special_format')
def handle_process_special_format(data):
    sender_id = data['clientId']
    special_lines = data['matches']

    for line in special_lines:
        user_text = line
        current_markdown = shared_content['markdown']
        prompt = f"\n\nUser request regarding the text:\n{user_text}{turn_assistant}"

        # Truncate the context
        truncated_context = truncate_context(shared_content['markdown'], f"=\\{user_text}\\", max_context_length=1024)
        full_prompt = f"{prompt_base}\n...{truncated_context}...{prompt}"
        print(full_prompt)
        placeholder = "=> "
        updated_markdown = current_markdown.replace(f'=\\{line}\\', placeholder, 1)
        diffs = dmp.diff_main(current_markdown, updated_markdown)
        if diffs:
            dmp.diff_cleanupSemantic(diffs)
            patches = dmp.patch_make(current_markdown, diffs)
            patch_text = dmp.patch_toText(patches)

            shared_content['markdown'] = updated_markdown
            emit('patch_update', {'patchText': patch_text, 'senderId': 'llm'}, broadcast=True)
            socketio.sleep(0)

        # Generate text using the language model
        full_str = ""
        # print(full_prompt)
        for output in llm(
                full_prompt,
                max_tokens=2048,
                stop=["<|end|>", "<end_of_turn>", "<|eot_id|>"],
                stream=True,
                temperature=0.5,
                top_p=0.9,
                repeat_penalty=1.15,
                top_k=20,
        ):
            token_str = output["choices"][0]["text"]
            print(token_str, end="", flush=True)

            current_markdown = shared_content['markdown']
            if len(full_str) == 0:
                updated_markdown = current_markdown.replace(placeholder + full_str,
                                                            placeholder + full_str + token_str + "<=|", 1)
            else:
                updated_markdown = current_markdown.replace(placeholder + full_str + "<=|",
                                                            placeholder + full_str + token_str + "<=|", 1)
            # print(current_markdown, updated_markdown)

            diffs = dmp.diff_main(current_markdown, updated_markdown)
            if diffs and (("<=|" in current_markdown and "=>" in current_markdown) or len(full_str) == 0):
                full_str += token_str
                dmp.diff_cleanupSemantic(diffs)
                patches = dmp.patch_make(current_markdown, diffs)
                patch_text = dmp.patch_toText(patches)

                shared_content['markdown'] = updated_markdown
                emit('patch_update', {'patchText': patch_text, 'senderId': "llm"}, broadcast=True)
                socketio.sleep(0.1)
            else:
                print("BREAK")
                break

        current_markdown = shared_content['markdown']
        updated_markdown = current_markdown.replace(placeholder + full_str + token_str + "<=|=", full_str, 1)
        diffs = dmp.diff_main(current_markdown, updated_markdown)
        if diffs:
            dmp.diff_cleanupSemantic(diffs)
            patches = dmp.patch_make(current_markdown, diffs)
            patch_text = dmp.patch_toText(patches)

            shared_content['markdown'] = updated_markdown
            emit('patch_update', {'patchText': patch_text, 'senderId': "llm"}, broadcast=True)
            socketio.sleep(0)
    current_markdown = shared_content['markdown']
    updated_markdown = current_markdown.replace(placeholder + full_str + token_str + "<=|", full_str, 1)
    diffs = dmp.diff_main(current_markdown, updated_markdown)
    if diffs:
        dmp.diff_cleanupSemantic(diffs)
        patches = dmp.patch_make(current_markdown, diffs)
        patch_text = dmp.patch_toText(patches)

        shared_content['markdown'] = updated_markdown
        emit('patch_update', {'patchText': patch_text, 'senderId': "llm"}, broadcast=True)
        socketio.sleep(0)


if __name__ == '__main__':
    socketio.run(app, debug=True, host="0.0.0.0", allow_unsafe_werkzeug=True)
