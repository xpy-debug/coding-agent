/**
 * Message editor component — textarea + send button + file upload.
 */

import { createAttachmentTile } from './attachment-tile.js';

/**
 * Initialize the message editor.
 * @param {HTMLElement} container - Where to render
 * @param {object} callbacks
 * @param {Function} callbacks.onSend - (text, attachments) => void
 * @param {Function} callbacks.onAbort - () => void
 * @param {Function} callbacks.getIsStreaming - () => boolean
 */
export function initMessageEditor(container, callbacks) {
    const { onSend, onAbort, getIsStreaming } = callbacks;
    let attachments = [];

    container.innerHTML = `
        <div class="composer relative">
            <div id="editor-attachments" class="hidden px-4 pt-3 pb-2 flex flex-wrap gap-2"></div>
            <textarea
                id="editor-textarea"
                class="w-full bg-transparent px-4 pt-3.5 pb-1.5 text-foreground placeholder-muted-foreground outline-none resize-none overflow-y-auto text-sm leading-relaxed"
                placeholder="Type a message..."
                rows="1"
                style="max-height: 200px; min-height: 1lh;"
            ></textarea>
            <input id="file-input" type="file" multiple accept="image/*,application/pdf,.txt,.md,.json,.xml,.html,.css,.js,.ts,.py" style="display:none">
            <div class="px-2.5 pb-2.5 flex items-center justify-between">
                <div class="flex items-center gap-1">
                    <button id="btn-attach" class="composer-action" title="Attach file" aria-label="Attach file">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                        </svg>
                    </button>
                </div>
                <div class="flex items-center gap-1">
                    <button id="btn-stop" class="composer-action hidden" title="Stop" aria-label="Stop">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <rect x="4" y="4" width="16" height="16" rx="3"/>
                        </svg>
                    </button>
                    <button id="btn-send" class="send-btn" title="Send" aria-label="Send">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 19V5M5 12l7-7 7 7"/>
                        </svg>
                    </button>
                </div>
            </div>
        </div>
    `;

    const textarea = container.querySelector('#editor-textarea');
    const sendBtn = container.querySelector('#btn-send');
    const stopBtn = container.querySelector('#btn-stop');
    const attachBtn = container.querySelector('#btn-attach');
    const fileInput = container.querySelector('#file-input');
    const attachmentsContainer = container.querySelector('#editor-attachments');

    function renderAttachments() {
        attachmentsContainer.innerHTML = '';
        if (attachments.length === 0) {
            attachmentsContainer.classList.add('hidden');
            return;
        }
        attachmentsContainer.classList.remove('hidden');
        for (const att of attachments) {
            attachmentsContainer.appendChild(createAttachmentTile(att, {
                showDelete: true,
                onDelete: (id) => {
                    attachments = attachments.filter(a => a.id !== id);
                    renderAttachments();
                },
            }));
        }
    }

    function send() {
        const text = textarea.value.trim();
        if ((!text && attachments.length === 0) || getIsStreaming()) return;
        onSend(text, [...attachments]);
        textarea.value = '';
        textarea.style.height = 'auto';
        attachments = [];
        renderAttachments();
        textarea.focus();
    }

    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (getIsStreaming()) return;
            send();
        } else if (e.key === 'Escape' && getIsStreaming()) {
            e.preventDefault();
            onAbort();
        }
    });

    sendBtn.addEventListener('click', send);
    stopBtn.addEventListener('click', onAbort);

    attachBtn.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', async () => {
        const files = Array.from(fileInput.files || []);
        for (const file of files) {
            if (file.size > 20 * 1024 * 1024) {
                alert(`${file.name} exceeds 20MB limit`);
                continue;
            }
            // Upload to server
            const formData = new FormData();
            formData.append('file', file);

            try {
                const resp = await fetch('/api/upload', { method: 'POST', body: formData });
                if (resp.ok) {
                    const data = await resp.json();
                    attachments.push({
                        id: data.id,
                        fileName: data.fileName,
                        mimeType: data.mimeType,
                        size: data.size,
                        previewUrl: data.mimeType?.startsWith('image/') ? URL.createObjectURL(file) : null,
                    });
                    renderAttachments();
                }
            } catch (e) {
                console.error('Upload failed:', e);
            }
        }
        fileInput.value = '';
    });

    // Drag and drop
    const editorEl = container.querySelector('.composer');
    editorEl.addEventListener('dragover', (e) => {
        e.preventDefault();
        editorEl.classList.add('is-dragging');
    });
    editorEl.addEventListener('dragleave', () => {
        editorEl.classList.remove('is-dragging');
    });
    editorEl.addEventListener('drop', async (e) => {
        e.preventDefault();
        editorEl.classList.remove('is-dragging');
        const files = Array.from(e.dataTransfer?.files || []);
        for (const file of files) {
            if (file.size > 20 * 1024 * 1024) continue;
            const formData = new FormData();
            formData.append('file', file);
            try {
                const resp = await fetch('/api/upload', { method: 'POST', body: formData });
                if (resp.ok) {
                    const data = await resp.json();
                    attachments.push({
                        id: data.id,
                        fileName: data.fileName,
                        mimeType: data.mimeType,
                        size: data.size,
                        previewUrl: data.mimeType?.startsWith('image/') ? URL.createObjectURL(file) : null,
                    });
                    renderAttachments();
                }
            } catch (e) {
                console.error('Upload failed:', e);
            }
        }
    });

    return {
        updateState(isStreaming) {
            sendBtn.classList.toggle('hidden', isStreaming);
            stopBtn.classList.toggle('hidden', !isStreaming);
            textarea.disabled = isStreaming;
        },
        focus() {
            textarea.focus();
        },
        clear() {
            textarea.value = '';
            attachments = [];
            renderAttachments();
        },
    };
}
