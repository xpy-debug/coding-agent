/**
 * Main application controller.
 * Connects WebSocket, state, and UI components.
 */

import { WebSocketClient } from './ws.js';
import { State } from './state.js';
import { renderMessageList, buildToolResultsMap } from './components/message-list.js';
import { initMessageEditor } from './components/message-editor.js';
import { updateStreamingMessage } from './components/streaming-message.js';
import { formatUsage, getAggregateUsage } from './utils/format.js';
import { showModelSelector } from './dialogs/model-selector.js';
import { initSessionSidebar } from './components/session-sidebar.js';
import {
    CUSTOM_VENDOR_ID,
    findVendor,
    getVendorChoices,
    needsBaseUrl,
    renderVendorEndpoint,
    vendorOptionsHtml,
    vendorSaveMessage,
} from './dialogs/provider-form.js';
import { initTheme, toggleTheme } from './utils/theme.js';
import { renderArtifactsPanel } from './artifacts/artifacts-panel.js';
import { showSettingsDialog } from './dialogs/settings.js';

// --- Globals ---
const ws = new WebSocketClient();
const state = new State();
let editor = null;
let autoScroll = true;

// --- DOM refs ---
const messagesContainer = document.getElementById('messages-container');
const messageListEl = document.getElementById('message-list');
const streamingContainer = document.getElementById('streaming-container');
const editorContainer = document.getElementById('message-editor');
const statsEl = document.getElementById('stats');
const modelNameEl = document.getElementById('model-name');
const thinkingLevelEl = document.getElementById('thinking-level');
const btnNewSession = document.getElementById('btn-new-session');
const btnModel = document.getElementById('btn-model');
const btnThinking = document.getElementById('btn-thinking');
const btnApproval = document.getElementById('btn-approval');
const approvalModeEl = document.getElementById('approval-mode');
const btnTheme = document.getElementById('btn-theme');
const btnSettings = document.getElementById('btn-settings');

// API key dialog
const apiKeyDialog = document.getElementById('api-key-dialog');
const apiKeyProviderSelect = document.getElementById('api-key-provider');
const apiKeyInput = document.getElementById('api-key-input');
const apiKeyHint = document.getElementById('api-key-hint');
const apiKeyBaseUrlGroup = document.getElementById('api-key-base-url-group');
const apiKeyBaseUrl = document.getElementById('api-key-base-url');
const apiKeyError = document.getElementById('api-key-error');
const apiKeySave = document.getElementById('api-key-save');
const apiKeyCancel = document.getElementById('api-key-cancel');

/** Vendors currently offered in the API key dialog. */
let apiKeyVendors = [];

// --- Init editor ---
editor = initMessageEditor(editorContainer, {
    onSend: (text, attachments = []) => {
        const attachmentIds = attachments.map(a => a.id);
        ws.send({ type: 'prompt', text, attachments: attachmentIds });
        autoScroll = true;
    },
    onAbort: () => {
        ws.send({ type: 'abort' });
    },
    getIsStreaming: () => state.isStreaming,
});

// --- Session sidebar ---
const sidebar = initSessionSidebar({
    onSelect: (sessionId) => {
        ws.send({ type: 'load_session', sessionId });
        autoScroll = true;
    },
    onDelete: (sessionId) => {
        ws.send({ type: 'delete_session', sessionId });
    },
});

// --- Auto-scroll logic ---
messageListEl.addEventListener('scroll', () => {
    const { scrollTop, scrollHeight, clientHeight } = messageListEl;
    const distFromBottom = scrollHeight - scrollTop - clientHeight;
    if (distFromBottom > 50) {
        autoScroll = false;
    } else if (distFromBottom < 10) {
        autoScroll = true;
    }
});

function scrollToBottom() {
    if (autoScroll) {
        messageListEl.scrollTop = messageListEl.scrollHeight;
    }
}

// --- Render functions ---
function renderMessages() {
    renderMessageList(messagesContainer, state.messages, {
        pendingToolCalls: state.pendingToolCalls,
        isStreaming: state.isStreaming,
        approvals: state.pendingApprovals,
        onDecide: decideApproval,
    });
    scrollToBottom();
}

/** Answer a tool approval request and send it to the server. */
function decideApproval({ toolCallId, approved, alwaysAllowTool }) {
    state.clearPendingApproval(toolCallId);
    if (approved) {
        state.addPendingToolCall(toolCallId);
    }
    renderMessages();
    ws.send({ type: 'tool_approval_reply', toolCallId, approved, alwaysAllowTool });
}

function renderStreamingMessage() {
    const toolResultsById = buildToolResultsMap(state.messages);
    updateStreamingMessage(
        streamingContainer,
        state.streamMessage,
        state.isStreaming,
        toolResultsById,
        new Set(),
    );
    scrollToBottom();
}

function renderStats() {
    const usage = getAggregateUsage(state.messages);
    const text = formatUsage(usage);
    statsEl.textContent = text;
}

function renderHeader() {
    approvalModeEl.textContent = state.approvalMode || 'auto';
    if (state.model) {
        modelNameEl.textContent = state.model.id || 'Unknown model';
        // Show thinking button if model supports reasoning
        if (state.model.reasoning) {
            btnThinking.classList.remove('hidden');
            thinkingLevelEl.textContent = state.thinkingLevel || 'off';
        } else {
            btnThinking.classList.add('hidden');
        }
    } else {
        modelNameEl.textContent = 'No model';
        btnThinking.classList.add('hidden');
    }
}

// --- WebSocket event handlers ---
ws.on('state', (data) => {
    state.applyState(data);
    renderMessages();
    renderHeader();
    renderStats();
    sidebar.setSessions(state.sessions, state.sessionId);
    editor.updateState(state.isStreaming);
});

ws.on('models', (data) => {
    state.applyModels(data);
});

ws.on('sessions', (data) => {
    state.applySessions(data);
    sidebar.setSessions(state.sessions, state.sessionId);
});

ws.on('agent_start', () => {
    state.setStreaming(true);
    editor.updateState(true);
});

ws.on('agent_end', () => {
    state.setStreaming(false);
    state.streamMessage = null;
    // Nothing is executing any more, so no card may keep spinning.
    state.resetPendingWork();
    streamingContainer.classList.add('hidden');
    editor.updateState(false);
    renderMessages();
    renderStats();
});

ws.on('message_start', (data) => {
    state.setStreamMessage(data.message);
    renderStreamingMessage();
});

ws.on('message_update', (data) => {
    state.streamMessage = data.message;
    renderStreamingMessage();
});

ws.on('message_end', (data) => {
    state.streamMessage = null;
    state.messages = [...state.messages, data.message];
    streamingContainer.classList.add('hidden');
    renderMessages();
    renderStats();
});

ws.on('tool_approval_request', (data) => {
    state.addPendingApproval(data);
    renderMessages();
    scrollToBottom();
});

ws.on('tool_start', (data) => {
    state.clearPendingApproval(data.toolCallId);
    state.addPendingToolCall(data.toolCallId);
    renderMessages();
});

ws.on('tool_end', (data) => {
    state.clearPendingApproval(data.toolCallId);
    state.clearPendingToolCall(data.toolCallId);
    renderMessages();
});

ws.on('error', (data) => {
    console.error('Server error:', data.message);
    // A modal dialog renders above the notification toast, so report failures
    // of the provider form inside the form itself.
    if (apiKeyDialog.open) {
        showApiKeyError(data.message);
        return;
    }
    showNotification(data.message, 'error');
});

ws.on('api_key_required', (data) => {
    showApiKeyDialog(data.provider);
});
ws.on('api_key_saved', (data) => {
    if (data && data.provider) {
        if (data.baseUrl) {
            state.baseUrls[data.provider] = data.baseUrl;
        } else {
            delete state.baseUrls[data.provider];
        }
    }
    apiKeyDialog.close();
});

ws.on('artifacts', (data) => {
    const artifactsPanel = document.getElementById('artifacts-panel');
    const messagesPanel = document.getElementById('messages-panel');
    const artifacts = data.artifacts || [];

    if (artifacts.length > 0) {
        messagesPanel.style.width = '50%';
        renderArtifactsPanel(artifactsPanel, artifacts, () => {
            artifactsPanel.classList.add('hidden');
            messagesPanel.style.width = '100%';
        });
    } else {
        artifactsPanel.classList.add('hidden');
        messagesPanel.style.width = '100%';
    }
});

// --- API Key Dialog ---
function selectedVendor() {
    return findVendor(apiKeyVendors, apiKeyProviderSelect.value);
}

/** Show or hide the Base URL input to match the selected vendor. */
function syncApiKeyForm() {
    const vendor = selectedVendor();
    const wantsUrl = needsBaseUrl(vendor);

    apiKeyBaseUrlGroup.classList.toggle('hidden', !wantsUrl);
    apiKeyHint.classList.toggle('hidden', wantsUrl);
    apiKeyBaseUrl.value = wantsUrl ? (state.baseUrls[vendor.id] || '') : '';
    apiKeyError.classList.add('hidden');

    if (!wantsUrl) {
        renderVendorEndpoint(apiKeyHint, vendor);
    }
}

function showApiKeyDialog(provider) {
    apiKeyVendors = getVendorChoices(state.vendors, provider);
    const selectedId = apiKeyVendors.some(v => v.id === provider) ? provider : CUSTOM_VENDOR_ID;
    apiKeyProviderSelect.innerHTML = vendorOptionsHtml(apiKeyVendors, selectedId);
    apiKeyInput.value = '';
    syncApiKeyForm();
    apiKeyDialog.showModal();
    apiKeyInput.focus();
}

function showApiKeyError(message) {
    apiKeyError.textContent = message;
    apiKeyError.classList.remove('hidden');
}

function saveApiKey() {
    const vendor = selectedVendor();
    const key = apiKeyInput.value.trim();
    const wantsUrl = needsBaseUrl(vendor);
    const baseUrl = wantsUrl ? apiKeyBaseUrl.value.trim() : '';

    if (wantsUrl && !baseUrl) {
        showApiKeyError('Base URL is required for a custom endpoint.');
        return;
    }
    if (!key && !wantsUrl) {
        showApiKeyError('Enter an API key.');
        return;
    }
    ws.send(vendorSaveMessage(vendor, key, baseUrl));
}

apiKeyProviderSelect.addEventListener('change', syncApiKeyForm);

apiKeySave.addEventListener('click', saveApiKey);

apiKeyCancel.addEventListener('click', () => {
    apiKeyDialog.close();
});

apiKeyInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        saveApiKey();
    }
});

apiKeyBaseUrl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        saveApiKey();
    }
});

// --- Model selector ---
btnModel.addEventListener('click', () => {
    if (state.providers.length === 0) return;
    showModelSelector(state.providers, state.model, (provider, modelId) => {
        ws.send({ type: 'set_model', provider, modelId });
    });
});

// --- Thinking level selector ---
btnThinking.addEventListener('click', () => {
    const levels = ['off', 'minimal', 'low', 'medium', 'high'];
    const current = state.thinkingLevel || 'off';
    const idx = levels.indexOf(current);
    const next = levels[(idx + 1) % levels.length];
    ws.send({ type: 'set_thinking_level', level: next });
    state.thinkingLevel = next;
    thinkingLevelEl.textContent = next;
});

// --- Tool approval mode selector ---
btnApproval.addEventListener('click', () => {
    const next = state.approvalMode === 'ask' ? 'auto' : 'ask';
    state.setApprovalMode(next);
    approvalModeEl.textContent = next;
    ws.send({ type: 'set_approval_mode', mode: next });
});

// --- Session management ---
btnNewSession.addEventListener('click', () => {
    ws.send({ type: 'new_session' });
    autoScroll = true;
});

// --- Settings ---
btnSettings.addEventListener('click', () => {
    showSettingsDialog({
        vendors: state.vendors,
        configuredProviders: state.configuredProviders,
        baseUrls: state.baseUrls,
        onSave: (message) => ws.send(message),
        onDelete: (provider) => ws.send({ type: 'delete_api_key', provider }),
    });
});

// --- Theme toggle ---
initTheme();
btnTheme.addEventListener('click', () => {
    toggleTheme();
});

// --- Notification helper ---
function showNotification(message, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast fixed top-4 right-4 z-50 px-4 py-2.5 rounded-xl border shadow-lg text-sm max-w-sm ${
        type === 'error'
            ? 'bg-destructive text-destructive-foreground border-destructive'
            : 'bg-card text-card-foreground border-border'
    }`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// --- Start ---
ws.connect();
editor.focus();
