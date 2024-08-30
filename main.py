##TODO: Math and code inlines and blocks should not be parsed!
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
    model_path="gemma-2-2b-it-Q5_K_M.gguf",
    verbose=False,
    n_threads=8,
    n_ctx=8128,
    n_batch=1024,
    n_gpu_layers=1000
)

# Store the markdown content
shared_content = {"markdown": ""}
dmp = dmp_module.diff_match_patch()

turn_system = "<start_of_turn>user\n"
turn_user = "<end_of_turn>\n<start_of_turn>user\n"
turn_assistant = "<end_of_turn>\n<start_of_turn>model\n"
prompt_base = f"{turn_system}You help to write conspect. You can use tables, blockquotes, lists, formulas (in the following format: $<math>$), code, and other formatting. Be conscise, answer as shorlty as possible, use formatting where possible. Answer without referencing user, just proceed to request"


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
    # print(data)
    # print(special_lines)
    for line in special_lines:
        # Prepare the prompt for the language model
        user_text = line
        prompt = prompt_base + "\n" + shared_content[
            'markdown'] + f"\n\nUser request regarding the text:\n{user_text}{turn_assistant}"

        # Create an initial patch to remove the special format line and replace with placeholder
        current_markdown = shared_content['markdown']
        placeholder = "=> "
        updated_markdown = current_markdown.replace(f'=\\{line}\\', placeholder, 1)
        # print(current_markdown, updated_markdown)
        diffs = dmp.diff_main(current_markdown, updated_markdown)
        if diffs:
            dmp.diff_cleanupSemantic(diffs)
            patches = dmp.patch_make(current_markdown, diffs)
            patch_text = dmp.patch_toText(patches)

            # Update the shared content with the placeholder
            shared_content['markdown'] = updated_markdown

            # Send the initial patch with the placeholder
            emit('patch_update', {'patchText': patch_text, 'senderId': 'llm'}, broadcast=True)
            socketio.sleep(0)  # Small sleep to let the event loop emit the message

        # Generate text using the language model
        full_str = ""
        print(prompt)
        for output in llm(
                prompt,
                max_tokens=8128,
                stop=["<|end|>", "<end_of_turn>", "<|eot_id|>"],
                stream=True,
                temperature=0.5,
                top_p=0.9,
                repeat_penalty=1.15,
                top_k=20,
        ):
            token_str = output["choices"][0]["text"]
            print(token_str, end="", flush=True)
            # Update the placeholder in real-time
            current_markdown = shared_content['markdown']
            if len(full_str) == 0:
                updated_markdown = current_markdown.replace(placeholder + full_str,
                                                            placeholder + full_str + token_str + "<=|", 1)
            else:
                updated_markdown = current_markdown.replace(placeholder + full_str + "<=|",
                                                            placeholder + full_str + token_str + "<=|", 1)
            print(current_markdown, updated_markdown)
            # print(updated_markdown)
            diffs = dmp.diff_main(current_markdown, updated_markdown)
            if diffs and (("<=|" in current_markdown and "=>" in current_markdown) or len(full_str) == 0):
                full_str += token_str
                dmp.diff_cleanupSemantic(diffs)
                patches = dmp.patch_make(current_markdown, diffs)
                patch_text = dmp.patch_toText(patches)

                # Update the shared content with the current generated text
                shared_content['markdown'] = updated_markdown

                # Stream the patch update to the frontend
                emit('patch_update', {'patchText': patch_text, 'senderId': "llm"}, broadcast=True)
                socketio.sleep(0.1)  # Small sleep to let the event loop emit the message
            else:
                print("BREAK")
                break

        current_markdown = shared_content['markdown']
        # print(current_markdown)
        updated_markdown = current_markdown.replace(placeholder + full_str + token_str + "<=|=", full_str, 1)
        diffs = dmp.diff_main(current_markdown, updated_markdown)
        if diffs:
            dmp.diff_cleanupSemantic(diffs)
            patches = dmp.patch_make(current_markdown, diffs)
            patch_text = dmp.patch_toText(patches)

            # Update the shared content with the current generated text
            shared_content['markdown'] = updated_markdown

            # Stream the patch update to the frontend
            emit('patch_update', {'patchText': patch_text, 'senderId': "llm"}, broadcast=True)
            socketio.sleep(0)  # Small sleep to let the event loop emit the message
    current_markdown = shared_content['markdown']
    # print(current_markdown)
    updated_markdown = current_markdown.replace(placeholder + full_str + token_str + "<=|", full_str, 1)
    diffs = dmp.diff_main(current_markdown, updated_markdown)
    if diffs:
        dmp.diff_cleanupSemantic(diffs)
        patches = dmp.patch_make(current_markdown, diffs)
        patch_text = dmp.patch_toText(patches)

        # Update the shared content with the current generated text
        shared_content['markdown'] = updated_markdown

        # Stream the patch update to the frontend
        emit('patch_update', {'patchText': patch_text, 'senderId': "llm"}, broadcast=True)
        socketio.sleep(0)  # Small sleep to let the event loop emit the message


if __name__ == '__main__':
    socketio.run(app, debug=True, host="0.0.0.0", allow_unsafe_werkzeug=True)
