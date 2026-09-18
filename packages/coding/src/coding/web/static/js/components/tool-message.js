/**
 * Tool call display component (collapsible).
 */

import { formatDuration } from '../utils/format.js';

/**
 * Render a tool call message.
 * @param {object} toolCall - ToolCall object {id, name, arguments}
 * @param {object} [options]
 * @param {object} [options.result] - ToolResultMessage
 * @param {boolean} [options.pending]
 * @param {boolean} [options.aborted]
 * @param {boolean} [options.isStreaming]
 * @param {object} [options.approval] - Pending approval request {toolName, args, reason}
 * @param {Function} [options.onDecide] - Called with {toolCallId, approved, alwaysAllowTool}
 * @returns {HTMLElement}
 */
export function renderToolMessage(toolCall, options = {}) {
    const {
        result,
        pending = false,
        aborted = false,
        isStreaming = false,
        approval = null,
        onDecide = null,
    } = options;
    const card = document.createElement('div');
    card.className = 'tool-card';

    // Header
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between gap-2 text-sm text-muted-foreground cursor-pointer';

    const left = document.createElement('div');
    left.className = 'flex items-center gap-2';

    // Status icon
    const status = document.createElement('span');
    if (approval) {
        status.className = 'text-warning';
        status.textContent = '\u25CF'; // filled circle
    } else if (pending || isStreaming) {
        status.className = 'inline-block w-3 h-3 border-2 border-muted-foreground border-t-transparent rounded-full animate-spin';
    } else if (result?.isError || aborted) {
        status.className = 'text-destructive';
        status.textContent = '\u2717'; // X mark
    } else if (result) {
        status.className = 'text-success';
        status.textContent = '\u2713'; // checkmark
    } else {
        status.textContent = '\u2022'; // bullet
    }
    left.appendChild(status);

    const name = document.createElement('span');
    name.textContent = toolCall.name || 'Tool call';
    left.appendChild(name);

    if (result && result.durationMs != null) {
        const duration = document.createElement('span');
        duration.className = 'text-xs text-muted-foreground/70';
        duration.textContent = formatDuration(result.durationMs);
        left.appendChild(duration);
    }

    if (approval) {
        const badge = document.createElement('span');
        badge.className = 'text-xs px-2 py-0.5 rounded-full bg-warning/15 text-warning';
        badge.textContent = '等待审批';
        left.appendChild(badge);
    }

    const chevron = document.createElement('span');
    chevron.className = 'text-xs text-muted-foreground transition-transform';
    chevron.textContent = '\u25BC'; // down arrow

    header.appendChild(left);
    header.appendChild(chevron);

    // Body (hidden by default)
    const body = document.createElement('div');
    body.className = 'hidden mt-3 flex flex-col gap-2';

    // Arguments
    const args = toolCall.arguments || {};
    if (Object.keys(args).length > 0) {
        const argsLabel = document.createElement('div');
        argsLabel.className = 'text-xs font-medium text-muted-foreground';
        argsLabel.textContent = 'Arguments';
        body.appendChild(argsLabel);

        const argsCode = document.createElement('pre');
        argsCode.className = 'text-xs bg-muted/60 border border-border p-2.5 rounded-lg overflow-x-auto';
        argsCode.textContent = JSON.stringify(args, null, 2);
        body.appendChild(argsCode);
    }

    // Result
    if (result) {
        const resultLabel = document.createElement('div');
        resultLabel.className = 'text-xs font-medium text-muted-foreground';
        resultLabel.textContent = result.isError ? 'Error' : 'Result';
        body.appendChild(resultLabel);

        const resultText = (result.content || [])
            .filter(c => c.type === 'text')
            .map(c => c.text)
            .join('\n');

        if (resultText) {
            const resultCode = document.createElement('pre');
            resultCode.className = `text-xs p-2.5 rounded-lg overflow-x-auto ${result.isError ? 'bg-destructive/10 text-destructive' : 'bg-muted/60 border border-border'}`;
            resultCode.textContent = resultText;
            body.appendChild(resultCode);
        }
    }

    if (aborted) {
        const abortedEl = document.createElement('div');
        abortedEl.className = 'text-xs text-destructive italic';
        abortedEl.textContent = 'Aborted';
        body.appendChild(abortedEl);
    }

    // Approval controls — the user decides before the tool is allowed to run
    if (approval && onDecide) {
        const actions = document.createElement('div');
        actions.className = 'flex flex-wrap items-center gap-2';

        if (approval.reason) {
            const reason = document.createElement('div');
            reason.className = 'text-xs text-muted-foreground w-full';
            reason.textContent = approval.reason;
            actions.appendChild(reason);
        }

        const decide = (approved, alwaysAllowTool) => {
            for (const button of actions.querySelectorAll('button')) {
                button.disabled = true;
            }
            onDecide({ toolCallId: toolCall.id, approved, alwaysAllowTool });
        };

        actions.appendChild(
            approvalButton('允许', 'bg-success text-background hover:opacity-90', () => decide(true, false)),
        );
        actions.appendChild(
            approvalButton('拒绝', 'bg-destructive text-destructive-foreground hover:opacity-90', () => decide(false, false)),
        );
        actions.appendChild(
            approvalButton(
                `本会话始终允许 ${toolCall.name}`,
                'bg-secondary text-secondary-foreground hover:bg-accent',
                () => decide(true, true),
            ),
        );

        body.appendChild(actions);
    }

    // Toggle (a pending approval opens itself so the command is visible)
    let expanded = Boolean(approval);
    if (expanded) {
        body.classList.remove('hidden');
        chevron.style.transform = 'rotate(180deg)';
    }

    header.addEventListener('click', () => {
        expanded = !expanded;
        body.classList.toggle('hidden', !expanded);
        chevron.style.transform = expanded ? 'rotate(180deg)' : '';
    });

    card.appendChild(header);
    card.appendChild(body);
    return card;
}

function approvalButton(label, className, onClick) {
    const button = document.createElement('button');
    button.className = `text-xs px-3.5 py-1.5 rounded-full font-medium transition-colors disabled:opacity-50 ${className}`;
    button.textContent = label;
    button.addEventListener('click', (event) => {
        event.stopPropagation();
        onClick();
    });
    return button;
}
