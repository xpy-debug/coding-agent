/**
 * Dark/light theme toggle.
 */

const STORAGE_KEY = 'coding-web-theme';

const HLJS_LIGHT = 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github.min.css';
const HLJS_DARK = 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css';

/** Apply a theme to the document, keeping the code theme in sync. */
function applyTheme(isDark) {
    document.documentElement.classList.toggle('dark', isDark);
    const link = document.getElementById('hljs-theme');
    if (link) {
        link.href = isDark ? HLJS_DARK : HLJS_LIGHT;
    }
}

/** Initialize theme from stored preference or system default */
export function initTheme() {
    const stored = localStorage.getItem(STORAGE_KEY);
    let isDark;
    if (stored === 'light') {
        isDark = false;
    } else if (stored === 'dark') {
        isDark = true;
    } else {
        isDark = !window.matchMedia('(prefers-color-scheme: light)').matches;
    }
    applyTheme(isDark);
}

/** Toggle between dark and light. Returns the resulting dark state. */
export function toggleTheme() {
    const isDark = !document.documentElement.classList.contains('dark');
    applyTheme(isDark);
    localStorage.setItem(STORAGE_KEY, isDark ? 'dark' : 'light');
    return isDark;
}
