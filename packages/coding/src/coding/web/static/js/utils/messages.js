/**
 * Wire-format helpers for agent messages.
 *
 * Messages arrive serialized with `by_alias=True`, so the discriminator fields
 * land under their aliases: a tool call is `{"toolCall": "tool_call", ...}` and
 * a tool result is `{"toolResult": "tool_result", ...}`. Neither carries a
 * `type` or `role` key, so checking those silently drops every tool card --
 * the call never renders and no success/failure mark appears.
 *
 * The alias spellings are accepted first; the plain ones stay as a fallback so
 * a message round-tripped through a different serializer still renders.
 */

/**
 * Is this assistant-content part a tool call?
 * @param {object} part
 * @returns {boolean}
 */
export function isToolCall(part) {
    return part?.toolCall === 'tool_call'
        || part?.type === 'toolCall'
        || part?.type === 'tool_call';
}

/**
 * Is this a tool result message?
 * @param {object} message
 * @returns {boolean}
 */
export function isToolResultMessage(message) {
    return message?.toolResult === 'tool_result'
        || message?.role === 'tool_result'
        || message?.role === 'toolResult';
}

/**
 * The tool call a result message belongs to.
 * @param {object} message
 * @returns {string}
 */
export function toolCallIdOf(message) {
    return message?.toolCallId || message?.tool_call_id || '';
}
