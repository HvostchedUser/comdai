// Download the content of the editor as a .md file
document.getElementById('download-md').addEventListener('click', function() {
    const content = editor.value;
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'document.md';
    link.click();
    URL.revokeObjectURL(url);
});

// Trigger the hidden file input when the upload button is clicked
document.getElementById('upload-md-btn').addEventListener('click', function() {
    document.getElementById('upload-md').click();
});
// Handle the uploaded file
document.getElementById('upload-md').addEventListener('change', function(event) {
    const file = event.target.files[0];
    if (file && file.name.endsWith('.md')) {
        const reader = new FileReader();
        reader.onload = function(e) {
            editor.value = e.target.result;
            renderMarkdown(editor.value);
        };
        reader.readAsText(file);
    } else {
        alert('Please upload a valid Markdown (.md) file.');
    }
});

document.getElementById('show-editor').addEventListener('click', function() {
    const editorContainer = document.getElementById('editor-container');
    const previewContainer = document.getElementById('preview-container');
    const showPreviewButton = document.getElementById('show-preview');
    const restorePanelsButton = document.getElementById('restore-panels');

    if (editorContainer.style.display !== 'none') {
        editorContainer.style.display = 'none';
        previewContainer.style.width = '100%'; // Expand preview to full width
        this.style.display = 'none';  // Hide this button
        showPreviewButton.style.display = 'none';  // Hide the show-preview button
        restorePanelsButton.style.display = 'block';  // Show the restore-panels button
    }
});

document.getElementById('show-preview').addEventListener('click', function() {
    const previewContainer = document.getElementById('preview-container');
    const editorContainer = document.getElementById('editor-container');
    const showEditorButton = document.getElementById('show-editor');
    const restorePanelsButton = document.getElementById('restore-panels');

    if (previewContainer.style.display !== 'none') {
        previewContainer.style.display = 'none';
        editorContainer.style.width = '100%'; // Expand editor to full width
        this.style.display = 'none';  // Hide this button
        showEditorButton.style.display = 'none';  // Hide the show-editor button
        restorePanelsButton.style.display = 'block';  // Show the restore-panels button
    }
});

document.getElementById('restore-panels').addEventListener('click', function() {
    const editorContainer = document.getElementById('editor-container');
    const previewContainer = document.getElementById('preview-container');
    const showEditorButton = document.getElementById('show-editor');
    const showPreviewButton = document.getElementById('show-preview');

    editorContainer.style.display = 'block';
    previewContainer.style.display = 'block';
    editorContainer.style.width = '50%';
    previewContainer.style.width = '50%';
    this.style.display = 'none';  // Hide this button
    showEditorButton.style.display = 'block';  // Show the show-editor button
    showPreviewButton.style.display = 'block';  // Show the show-preview button
});


const socket = io.connect('http://' + document.domain + ':' + location.port);
const editor = document.getElementById('editor');
editor.value = "";
const preview = document.getElementById('preview');

const clientId = Math.random().toString(36).substr(2, 9); // Unique client ID
let lastContent = editor.value; // Initial content
let patchQueue = [];  // Unified queue for both local and remote patches
let isProcessingQueue = false;  // Flag to check if the worker is processing the queue



// Initialize diff-match-patch
const dmp = new diff_match_patch();

function addPatchToQueue(patch) {
    patchQueue.push(patch);
    processPatchQueue();  // Process the patch immediately
}

function renderAccumulatedPatches() {
    if (patchQueue.length === 0) return;

    const selection = saveSelection();

    let finalContent = lastContent;
    let combinedPatch = [];

    patchQueue.forEach(patch => {
        finalContent = patch.newContent;
        combinedPatch.push(...dmp.patch_make(patch.oldContent, patch.newContent));
    });

    renderMarkdown(finalContent);
    editor.value = finalContent;

    const adjustedSelection = adjustSelection(selection, combinedPatch);
    restoreSelection(adjustedSelection);

    patchQueue = [];
}


function processPatchQueue() {
    if (patchQueue.length === 0) {
        return;
    }

    const patch = patchQueue.shift();  // Get the next patch

    if (patch.isLocal) {
        const diffs = dmp.diff_main(lastContent, patch.content);
        if (diffs.length > 0) {
            dmp.diff_cleanupSemantic(diffs);
            const patches = dmp.patch_make(lastContent, diffs);
            const patchText = dmp.patch_toText(patches);

            socket.emit('markdown_patch', { patchText, clientId });
            checkSpecialFormat(patch.content);

            lastContent = patch.content;

            renderMarkdown(lastContent);

        }
    } else {
        // Save current selection
        const selection = saveSelection();

        // Apply the patch
        const appliedPatch = dmp.patch_apply(patch.patch, lastContent);
        const newContent = appliedPatch[0];

        // Adjust the selection based on the patch
        const adjustedSelection = adjustSelection(selection, patch.patch);

        lastContent = newContent;
        editor.value = newContent;

        // Restore the adjusted selection
        restoreSelection(adjustedSelection);

        renderMarkdown(newContent);
    }
}


    // Convert markdown to HTML and render LaTeX
function renderMarkdown(text) {
    text = text.replace(/=>\s*[a-f0-9\-]+\n/g, '=>');
    const previewContainer = document.getElementById('preview-container');


    const previousScrollTop = previewContainer.scrollTop;
    const previousHeight = previewContainer.scrollHeight;


    const placeholders = [];

    // Helper function to store and replace code/math content with a placeholder
    function storePlaceholder(content) {
        const placeholder = `<nomd>block-${placeholders.length}<nomd>`;
        placeholders.push(content);
        return placeholder;
    }

    // Handle block LaTeX (MathJax)
    text = text.replace(/^\$\$(.*?)\$\$/gms, (_, math) => storePlaceholder(`<div class="math">\\[${math}\\]</div>`));

    // Handle inline LaTeX (MathJax)
    text = text.replace(/\$(.*?)\$/g, (_, math) => storePlaceholder(`<span class="math">\\(${math}\\)</span>`));

    // Handle code blocks with or without language highlighting
    try {
        text = text.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
            const highlightedCode = lang
                ? `<pre class="language-${lang}"><code class="language-${lang}">${Prism.highlight(code, Prism.languages[lang] || Prism.languages.plain, lang)}</code><span class="lang-label">${lang}</span></pre>`
                : `<pre><code>${Prism.highlight(code, Prism.languages.plain, 'plain')}</code></pre>`;
            return storePlaceholder(highlightedCode);
        });
    } catch (error) {
        text = text.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
            const highlightedCode = lang
                ? `<pre class="language-${lang}"><code class="language-${lang}">${Prism.highlight(code, Prism.languages[lang] || Prism.languages.plain, lang)}</code><span class="lang-label">${lang}</span></pre>`
                : `<pre><code>${Prism.highlight(code, Prism.languages.plain, 'plain')}</code></pre>`;
            return storePlaceholder(highlightedCode);
        });
    }

    // Now, process the rest of the markdown
    // Handle custom block between => and <=|, replacing => with a throbber
    text = text.replace(/^=>\s*$/gm, '<div class="custom-block"><span class="throbber"></span></div>');
    text = text.replace(/=>\s*([\s\S]*?)\s*<=\|/g, '<div class="custom-block"><span class="throbber"></span> $1</div>');

    // Handle headers
    text = text
        .replace(/^###### (.*$)/gim, '<h6>$1</h6>')
        .replace(/^##### (.*$)/gim, '<h5>$1</h5>')
        .replace(/^#### (.*$)/gim, '<h4>$1</h4>')
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/^## (.*$)/gim, '<h2>$1</h2>')
        .replace(/^# (.*$)/gim, '<h1>$1</h1>');

    // Handle blockquotes
    text = text.replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>');

    function processLists(text) {
        const lines = text.split('\n');
        let result = '';
        let listStack = []; // Stack to keep track of opened lists
        let previousIndent = 0;

        lines.forEach(line => {
            const unorderedMatch = line.match(/^(\s*)([-*])\s+(.*)/);
            const orderedMatch = line.match(/^(\s*)(\d+\.)\s+(.*)/);

            if (unorderedMatch) {
                const indent = unorderedMatch[1].length + 1;
                const content = unorderedMatch[3];

                if (indent > previousIndent) {
                    result += `<ul>\n<li>${content}</li>\n`;
                    listStack.push('ul');
                } else if (indent < previousIndent) {
                    while (indent < previousIndent && listStack.length > 0) {
                        result += `</${listStack.pop()}>\n`;
                        previousIndent -= 4;
                    }
                    result += `<li>${content}</li>\n`;
                } else {
                    result += `<li>${content}</li>\n`;
                }
                previousIndent = indent;

            } else if (orderedMatch) {
                const indent = orderedMatch[1].length + 1;
                const content = orderedMatch[3];

                if (indent > previousIndent) {
                    result += `<ol>\n<li>${content}</li>\n`;
                    listStack.push('ol');
                } else if (indent < previousIndent) {
                    while (indent < previousIndent && listStack.length > 0) {
                        result += `</${listStack.pop()}>\n`;
                        previousIndent -= 4;
                    }
                    result += `<li>${content}</li>\n`;
                } else {
                    result += `<li>${content}</li>\n`;
                }
                previousIndent = indent;

            } else {
                // If it's not a list, close any open lists
                while (listStack.length > 0) {
                    result += `</${listStack.pop()}>\n`;
                }
                result += `${line}\n`;
                previousIndent = 0;
            }
        });

        // Close any remaining open lists at the end
        while (listStack.length > 0) {
            result += `</${listStack.pop()}>\n`;
        }

        return result;
    }

    // Replace lists in the text
    text = processLists(text);

    // Handle bold and italics
    text = text
        .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>') // bold with **
        .replace(/\*(.*?)\*/g, '<i>$1</i>')     // italic with *
        .replace(/__(.*?)__/g, '<b>$1</b>')     // bold with __
        .replace(/_(.*?)_/g, '<i>$1</i>');      // italic with _

    // Handle strikethrough with ~~
    text = text.replace(/\~\~(.*?)\~\~/g, '<del>$1</del>');

    // Handle horizontal rules (--- or any number of hyphens)
    text = text.replace(/^\s*[-]{3,}\s*$/gim, '<hr>');

    // Handle inline code
    text = text.replace(/\`(.*?)\`/gim, '<code>$1</code>');

    // Handle images (order matters here)
    text = text.replace(/\!\[(.*?)\]\((.*?)\)/gim, '<img src="$2" alt="$1">');

    // Handle links
    text = text.replace(/\[(.*?)\]\((.*?)\)/gim, '<a href="$2" target="_blank">$1</a>');


    // Handle tables
    text = text.replace(/^\|(.+)\|\s*\n\|([-|: ]+)\|\s*\n((?:\|.*\|\s*\n)*)/gim, function (match, header, align, body) {
        let headerCells = header.split('|').map(cell => `<th>${cell.trim()}</th>`).join('');
        let bodyRows = body.split('\n').filter(row => row).map(row => {
            let cells = row.split('|').slice(1, -1).map(cell => `<td>${cell.trim()}</td>`).join('');
            return `<tr>${cells}</tr>`;
        }).join('');
        return `<table><thead><tr>${headerCells}</tr></thead><tbody>${bodyRows}</tbody></table>`;
    });

    // Handle line breaks
    text = text.replace(/\n\n/g, '<br />');

    // Restore placeholders
    placeholders.forEach((content, index) => {
        text = text.replace(`<nomd>block-${index}<nomd>`, content);
    });

    // Set the preview content
    preview.innerHTML = text;

    // Trigger MathJax rendering if available
    if (window.MathJax) {
        MathJax.typesetPromise();
    }

    // After rendering, measure the new height of the preview container
    const newHeight = previewContainer.scrollHeight;

    // If the height has changed, adjust the scroll position accordingly
    const heightDifference = newHeight - previousHeight;

    // Restore the scroll position, adjusting it by the height difference
    previewContainer.scrollTop = previousScrollTop + heightDifference;

}
// Save and restore cursor position and selection range
function saveSelection() {
    return {
        start: editor.selectionStart,
        end: editor.selectionEnd
    };
}

function restoreSelection(selection) {
    editor.selectionStart = selection.start;
    editor.selectionEnd = selection.end;
    editor.focus();
}

function adjustSelection(selection, patches) {
    let newStart = selection.start;
    let newEnd = selection.end;

    patches.forEach(p => {
        let diffIndex = p.start1;
        p.diffs.forEach(diff => {
            const [op, data] = diff;
            const diffLength = data.length;

            if (op === -1) { // Deletion
                if (newStart > diffIndex) {
                    newStart -= Math.min(diffLength, newStart - diffIndex);
                }
                if (newEnd > diffIndex) {
                    newEnd -= Math.min(diffLength, newEnd - diffIndex);
                }
            } else if (op === 1) { // Insertion
                if (newStart >= diffIndex) {
                    newStart += diffLength;
                }
                if (newEnd >= diffIndex) {
                    newEnd += diffLength;
                }
            }

            if (op !== 0) {
                diffIndex += diffLength;
            }
        });
    });

    return { start: newStart, end: newEnd };
}


// Function to wrap new content with a span that will be animated
function highlightChanges(newText, oldText) {
    const diffOutput = dmp.diff_main(oldText, newText);
    dmp.diff_cleanupSemantic(diffOutput);

    let highlightedText = '';
    diffOutput.forEach(part => {
        const [op, text] = part;
        if (op === 0) { // Unchanged text
            highlightedText += text;
        } else if (op === 1) { // Added text
            const spanId = `highlight-${Math.random().toString(36).substr(2, 9)}`;
            highlightedText += `<span id="${spanId}" class="highlighted">${text}</span>`;
            removeHighlightAfterDelay(spanId);
        } else if (op === -1) { // Removed text (we don't render this in preview)
            // Optionally, you could keep track of removed text if needed.
        }
    });

    return highlightedText;
}

// Function to remove the highlight class after a delay
function removeHighlightAfterDelay(elementId) {
    setTimeout(() => {
        const element = document.getElementById(elementId);
        if (element) {
            element.classList.remove('highlighted');
        }
    }, 5000); // Delay in milliseconds
}




// Handle patch updates from the server
socket.on('patch_update', function({ patchText, senderId }) {
    if (senderId !== clientId) {
        const patch = dmp.patch_fromText(patchText);
        addPatchToQueue({ isLocal: false, patch });  // Add remote patch to the queue
    }
});

// Function to check for the special line format and send it to the backend for processing
// Function to check for the special multi-line format and send it to the backend for processing
function checkSpecialFormat(text) {
    // Regular expression to match multi-line prompts in the format `=\<multiline prompt>\=`
    const specialLineRegex = /^=\\([\s\S]*?)\\=$/gm;
    let matches = [];
    let match;

    while ((match = specialLineRegex.exec(text)) !== null) {
        matches.push(match[1]); // Store the content without the equals signs and trim any excess whitespace
    }

    // If we found matches, send them to the backend for processing
    if (matches.length > 0) {
        socket.emit('process_special_format', { matches, clientId });
    }
}

function adjustEditorScroll(editor) {
    const editorRect = editor.getBoundingClientRect();
    const lineHeight = editor.scrollHeight / editor.value.split('\n').length;

    // Calculate the number of visible lines
    const visibleLines = Math.floor(editor.clientHeight / lineHeight);

    // Get the cursor position in the text (index)
    const cursorPosition = editor.selectionStart;

    // Calculate which line the cursor is on
    const currentLine = editor.value.substr(0, cursorPosition).split("\n").length;

    // Calculate the current scroll position in terms of lines
    const scrollLineStart = editor.scrollTop / lineHeight;

    // Determine how many lines are from the current cursor to the bottom of the visible area
    const linesFromBottom = visibleLines - (currentLine - scrollLineStart);

    // If the cursor is less than 10 lines from the bottom, scroll up
    if (linesFromBottom < 10) {
        editor.scrollTop = (currentLine - visibleLines + 10) * lineHeight;
    }
}

editor.addEventListener("input", function() {
    addPatchToQueue({ isLocal: true, content: editor.value });

    // Check if we need to add a new line and move cursor
    const cursorPosition = editor.selectionStart;
    const textBeforeCursor = editor.value.substring(0, cursorPosition);

    // Use regex to check if the text before the cursor ends with =\text\=
    const pattern = /=\\[\s\S]*?\\=$/;
    const match = textBeforeCursor.match(pattern);
    if (match && match.index + match[0].length === cursorPosition) {
        // The user just finished typing =\text\=
        // Insert a new line at the cursor position
        const textAfterCursor = editor.value.substring(cursorPosition);
        editor.value = textBeforeCursor + '\n\n' + textAfterCursor;

        // Move the cursor to the new line
        editor.selectionStart = editor.selectionEnd = cursorPosition + 2;

        // Update lastContent and render markdown
        lastContent = editor.value;
        renderMarkdown(editor.value);

        // Add the new change to the queue
        addPatchToQueue({ isLocal: true, content: editor.value });
    } else {
        // Render markdown for other inputs
        renderMarkdown(editor.value);
    }
});


// Initial render
renderMarkdown(editor.value);
