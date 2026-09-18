/**
 * Client-side state store.
 */

export class State {
    constructor() {
        this.sessionId = '';
        this.model = null;
        this.thinkingLevel = 'off';
        /** Tool approval mode: 'auto' runs everything, 'ask' requests consent. */
        this.approvalMode = 'auto';
        /** @type {Array} */
        this.messages = [];
        this.isStreaming = false;
        /** Current streaming message being built */
        this.streamMessage = null;
        /** Tool calls waiting for the user's consent, keyed by tool call id. */
        this.pendingApprovals = new Map();
        /** Tool call ids that are currently executing. */
        this.pendingToolCalls = new Set();
        /** @type {Array} */
        this.providers = [];
        /** Vendor presets offered by the server ({id, label, baseUrl, apiKeyUrl}). */
        this.vendors = [];
        /** Providers with stored credentials. */
        this.configuredProviders = [];
        /** Provider base URL overrides, keyed by provider name. */
        this.baseUrls = {};
        /** @type {Array} */
        this.sessions = [];
        /** @type {Set<Function>} */
        this._listeners = new Set();
    }

    /** Subscribe to state changes. Returns unsubscribe fn. */
    subscribe(fn) {
        this._listeners.add(fn);
        return () => this._listeners.delete(fn);
    }

    /** Notify all subscribers */
    notify() {
        for (const fn of this._listeners) {
            try { fn(this); } catch (e) { console.error('State listener error:', e); }
        }
    }

    /** Apply a full state update from server */
    applyState(data) {
        this.sessionId = data.sessionId || '';
        this.model = data.model || null;
        this.thinkingLevel = data.thinkingLevel || 'off';
        this.approvalMode = data.approvalMode || 'auto';
        this.messages = data.messages || [];
        this.isStreaming = data.isStreaming || false;
        this.streamMessage = null;
        this.pendingApprovals = new Map();
        this.pendingToolCalls = new Set();
        this.notify();
    }

    /** Apply models list from server */
    applyModels(data) {
        this.providers = data.providers || [];
        this.baseUrls = data.baseUrls || {};
        this.vendors = data.vendors || [];
        this.configuredProviders = data.configuredProviders || [];
        this.notify();
    }

    /** Apply sessions list from server */
    applySessions(data) {
        this.sessions = data.sessions || [];
        this.notify();
    }

    /** Start streaming */
    setStreaming(streaming) {
        this.isStreaming = streaming;
        if (!streaming) {
            this.streamMessage = null;
        }
        this.notify();
    }

    /** Update the current stream message */
    setStreamMessage(message) {
        this.streamMessage = message;
        this.notify();
    }

    /** Add a completed message to the list */
    addMessage(message) {
        this.messages = [...this.messages, message];
        this.notify();
    }

    /** Update the tool approval mode */
    setApprovalMode(mode) {
        this.approvalMode = mode;
        this.notify();
    }

    /** Record a tool call that is waiting for the user's consent */
    addPendingApproval(request) {
        const next = new Map(this.pendingApprovals);
        next.set(request.toolCallId, request);
        this.pendingApprovals = next;
        this.notify();
    }

    /** Drop an approval request that was answered or superseded */
    clearPendingApproval(toolCallId) {
        if (!this.pendingApprovals.has(toolCallId)) return;
        const next = new Map(this.pendingApprovals);
        next.delete(toolCallId);
        this.pendingApprovals = next;
        this.notify();
    }

    /** Record a tool call that started executing */
    addPendingToolCall(toolCallId) {
        if (!toolCallId || this.pendingToolCalls.has(toolCallId)) return;
        this.pendingToolCalls = new Set(this.pendingToolCalls).add(toolCallId);
        this.notify();
    }

    /** Drop a tool call that finished executing */
    clearPendingToolCall(toolCallId) {
        if (!this.pendingToolCalls.has(toolCallId)) return;
        const next = new Set(this.pendingToolCalls);
        next.delete(toolCallId);
        this.pendingToolCalls = next;
        this.notify();
    }

    /** Forget every in-flight approval and running tool call.
     *
     * A finished run has nothing executing and nothing left to answer, so any
     * leftover entry would spin forever (e.g. approving a call and then
     * aborting before it starts).
     */
    resetPendingWork() {
        this.pendingApprovals = new Map();
        this.pendingToolCalls = new Set();
        this.notify();
    }
}
