/**
 * Message list renderer — renders all completed messages.
 */

import { renderUserMessage } from './user-message.js';
import { renderAssistantMessage } from './assistant-message.js';
import { isToolResultMessage, toolCallIdOf } from '../utils/messages.js';

/**
 * Render the full message list into a container.
 * @param {HTMLElement} container
 * @param {Array} messages
 * @param {object} [options]
 * @param {Set} [options.pendingToolCalls]
 * @param {boolean} [options.isStreaming]
 * @param {Map} [options.approvals] - Pending approval requests by tool call id
 * @param {Function} [options.onDecide] - Approval callback
 */
export function renderMessageList(container, messages, options = {}) {
    const {
        pendingToolCalls = new Set(),
        isStreaming = false,
        approvals = new Map(),
        onDecide = null,
    } = options;

    // Build a map of tool results by call ID
    const toolResultsById = new Map();
    for (const msg of messages) {
        if (isToolResultMessage(msg)) {
            const id = toolCallIdOf(msg);
            if (id) toolResultsById.set(id, msg);
        }
    }

    container.innerHTML = '';

    for (const msg of messages) {
        if (msg.role === 'user' || msg.role === 'user-with-attachments') {
            container.appendChild(renderUserMessage(msg));
        } else if (msg.role === 'assistant') {
            container.appendChild(renderAssistantMessage(msg, {
                isStreaming: false,
                toolResultsById,
                pendingToolCalls,
                approvals,
                onDecide,
            }));
        }
        // tool_result messages are rendered inline with assistant messages
    }
}

/**
 * Build tool results map from messages.
 */
export function buildToolResultsMap(messages) {
    const map = new Map();
    for (const msg of messages) {
        if (isToolResultMessage(msg)) {
            const id = toolCallIdOf(msg);
            if (id) map.set(id, msg);
        }
    }
    return map;
}
