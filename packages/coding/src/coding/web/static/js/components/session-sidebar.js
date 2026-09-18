/**
 * Sliding session sidebar.
 *
 * Replaces the old modal session picker with a rail that slides in from the
 * left, so past conversations stay one tap away and the chat stays visible
 * while browsing them.
 */

const STORAGE_KEY = 'coding-web-sidebar-open';
const DESKTOP_MEDIA = '(min-width: 1024px)';

const ICON_TRASH = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
    </svg>`;

const ICON_CHAT = `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>
    </svg>`;

/**
 * Wire up the sidebar.
 * @param {object} options
 * @param {Function} options.onSelect - (sessionId) => void
 * @param {Function} options.onDelete - (sessionId) => void
 * @returns {{setSessions: Function, open: Function, close: Function, toggle: Function, isOpen: Function}}
 */
export function initSessionSidebar({ onSelect, onDelete }) {
    const aside = document.getElementById('session-sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    const listEl = document.getElementById('session-list');
    const countEl = document.getElementById('session-count');
    const closeBtn = document.getElementById('sidebar-close');
    const toggleBtn = document.getElementById('btn-sidebar');

    let sessions = [];
    let activeId = '';
    let open = false;

    function isDesktop() {
        return window.matchMedia(DESKTOP_MEDIA).matches;
    }

    function setOpen(next, persist = true) {
        open = next;
        document.body.classList.toggle('sidebar-open', open);
        toggleBtn?.setAttribute('aria-expanded', String(open));
        if (persist) {
            try {
                localStorage.setItem(STORAGE_KEY, open ? '1' : '0');
            } catch {
                /* storage unavailable: keep the in-memory state */
            }
        }
    }

    function formatDate(isoString) {
        if (!isoString) return '';
        const date = new Date(isoString);
        if (Number.isNaN(date.getTime())) return '';
        const days = Math.floor((Date.now() - date.getTime()) / (1000 * 60 * 60 * 24));
        if (days <= 0) return 'Today';
        if (days === 1) return 'Yesterday';
        if (days < 7) return `${days} days ago`;
        return date.toLocaleDateString();
    }

    function renderEmpty() {
        const empty = document.createElement('div');
        empty.className = 'sidebar-empty';

        const mark = document.createElement('div');
        mark.className = 'sidebar-empty__mark';
        mark.innerHTML = ICON_CHAT;

        const title = document.createElement('p');
        title.className = 'sidebar-empty__title';
        title.textContent = 'No chats yet';

        const hint = document.createElement('p');
        hint.className = 'sidebar-empty__hint';
        hint.textContent = 'Your conversations are saved here, so you can pick one up later.';

        empty.append(mark, title, hint);
        return empty;
    }

    function renderItem(session) {
        const item = document.createElement('div');
        item.className = 'session-item';
        item.dataset.id = session.id;
        item.setAttribute('role', 'button');
        item.setAttribute('tabindex', '0');
        if (session.id === activeId) {
            item.classList.add('is-active');
        }

        const body = document.createElement('div');
        body.className = 'min-w-0 flex-1';

        const title = document.createElement('div');
        title.className = 'session-item__title';
        title.textContent = session.title || 'Untitled chat';
        body.appendChild(title);

        const count = session.message_count || 0;
        const metaParts = [formatDate(session.last_modified)];
        if (count > 0) {
            metaParts.push(`${count} message${count === 1 ? '' : 's'}`);
        }
        const meta = document.createElement('div');
        meta.className = 'session-item__meta';
        meta.textContent = metaParts.filter(Boolean).join(' · ');
        body.appendChild(meta);

        if (session.preview) {
            const preview = document.createElement('div');
            preview.className = 'session-item__preview';
            preview.textContent = session.preview;
            body.appendChild(preview);
        }

        item.appendChild(body);

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'session-delete';
        deleteBtn.title = 'Delete chat';
        deleteBtn.setAttribute('aria-label', `Delete ${session.title || 'chat'}`);
        deleteBtn.innerHTML = ICON_TRASH;
        deleteBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            if (window.confirm(`Delete "${session.title || 'Untitled chat'}"? This cannot be undone.`)) {
                onDelete(session.id);
            }
        });
        item.appendChild(deleteBtn);

        const select = () => {
            onSelect(session.id);
            if (!isDesktop()) {
                setOpen(false);
            }
        };
        item.addEventListener('click', select);
        item.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                select();
            }
        });

        return item;
    }

    function render() {
        listEl.innerHTML = '';
        if (sessions.length === 0) {
            listEl.appendChild(renderEmpty());
        } else {
            for (const session of sessions) {
                listEl.appendChild(renderItem(session));
            }
        }
        if (countEl) {
            countEl.textContent = sessions.length > 0 ? String(sessions.length) : '';
        }
    }

    /** Replace the rendered list. `currentId` marks the open conversation. */
    function setSessions(nextSessions, currentId = '') {
        sessions = Array.isArray(nextSessions) ? nextSessions : [];
        activeId = currentId || '';
        render();
    }

    toggleBtn?.addEventListener('click', () => setOpen(!open));
    closeBtn?.addEventListener('click', () => setOpen(false));
    backdrop?.addEventListener('click', () => setOpen(false));
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && open && !document.querySelector('dialog[open]')) {
            setOpen(false);
        }
    });

    // Restore the last state, defaulting to visible on desktop so the history
    // is on screen without a click.
    let stored = null;
    try {
        stored = localStorage.getItem(STORAGE_KEY);
    } catch {
        /* storage unavailable */
    }
    setOpen(stored === null ? isDesktop() : stored === '1', false);

    render();

    return {
        setSessions,
        open: () => setOpen(true),
        close: () => setOpen(false),
        toggle: () => setOpen(!open),
        isOpen: () => open,
        element: aside,
    };
}
