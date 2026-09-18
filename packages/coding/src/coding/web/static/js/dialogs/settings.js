/**
 * Settings dialog — provider credentials.
 */

import {
    findVendor,
    getVendorChoices,
    needsBaseUrl,
    renderVendorEndpoint,
    vendorOptionsHtml,
    vendorSaveMessage,
} from './provider-form.js';

const INPUT_CLASS = 'w-full px-3 py-2 rounded-md border border-input bg-background text-foreground text-sm';

/**
 * Show the settings dialog.
 * @param {object} options
 * @param {Array} options.vendors - vendor presets from the server
 * @param {Array<string>} options.configuredProviders - providers with stored credentials
 * @param {Object} options.baseUrls - provider -> saved base URL override
 * @param {Function} options.onSave - (message) => void, forwarded to the server
 * @param {Function} options.onDelete - (provider) => void
 */
export function showSettingsDialog({ vendors, configuredProviders, baseUrls, onSave, onDelete }) {
    const overrides = baseUrls || {};
    const choices = getVendorChoices(vendors);
    let configured = [...(configuredProviders || [])];
    let activeVendorId = choices[0]?.id || '';

    const dialog = document.createElement('dialog');
    dialog.className = 'bg-card text-card-foreground border border-border rounded-xl shadow-xl backdrop:bg-black/50 max-w-lg w-full max-h-[90vh] flex flex-col';

    function render() {
        const vendor = findVendor(choices, activeVendorId);
        const wantsUrl = needsBaseUrl(vendor);

        dialog.innerHTML = `
            <div class="p-4 border-b border-border flex-shrink-0">
                <h2 class="text-lg font-semibold">Settings</h2>
                <p class="text-sm text-muted-foreground mt-1">Configure the model providers you want to use</p>
            </div>
            <div class="flex-1 overflow-y-auto p-4 space-y-4">
                <div class="space-y-2">
                    <label for="settings-provider" class="block text-xs font-medium text-muted-foreground">Provider</label>
                    <select id="settings-provider" class="${INPUT_CLASS}">
                        ${vendorOptionsHtml(choices, activeVendorId)}
                    </select>
                    <input id="settings-key" type="password" class="${INPUT_CLASS}" placeholder="API key...">
                    <div id="settings-url-group" class="${wantsUrl ? '' : 'hidden'}">
                        <input id="settings-url" type="text" class="${INPUT_CLASS}" placeholder="https://api.example.com/v1" value="${wantsUrl ? (overrides[vendor.id] || '') : ''}">
                        <p class="text-xs text-muted-foreground mt-1">Models are fetched from this endpoint when you save.</p>
                    </div>
                    <p id="settings-endpoint" class="text-xs text-muted-foreground ${wantsUrl ? 'hidden' : ''}"></p>
                    <p id="settings-error" class="hidden text-xs text-destructive"></p>
                    <button id="settings-save" class="w-full px-3 py-2 text-sm rounded-full bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity">Save</button>
                </div>
                <div>
                    <h3 class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Configured</h3>
                    ${configured.length
                        ? configured.map(name => `
                            <div class="flex items-center justify-between gap-2 px-2 py-2 rounded-lg hover:bg-secondary transition-colors">
                                <div class="min-w-0">
                                    <div class="text-sm text-foreground truncate">${name}</div>
                                    ${overrides[name] ? `<div class="text-xs text-muted-foreground truncate">${overrides[name]}</div>` : ''}
                                </div>
                                <button class="remove-provider text-xs text-muted-foreground hover:text-destructive px-2.5 py-1 rounded-full whitespace-nowrap transition-colors" data-provider="${name}">Remove</button>
                            </div>
                        `).join('')
                        : '<div class="text-sm text-muted-foreground">No providers configured yet</div>'}
                </div>
            </div>
            <div class="p-4 border-t border-border flex justify-end flex-shrink-0">
                <button class="close-btn px-4 py-1.5 text-sm rounded-full border border-border hover:bg-secondary transition-colors">Close</button>
            </div>
        `;

        if (!wantsUrl) {
            renderVendorEndpoint(dialog.querySelector('#settings-endpoint'), vendor);
        }
        bindEvents();
    }

    function showError(message) {
        const el = dialog.querySelector('#settings-error');
        if (el) {
            el.textContent = message;
            el.classList.remove('hidden');
        }
    }

    function save() {
        const vendor = findVendor(choices, activeVendorId);
        const wantsUrl = needsBaseUrl(vendor);
        const key = dialog.querySelector('#settings-key')?.value.trim() || '';
        const baseUrl = wantsUrl ? (dialog.querySelector('#settings-url')?.value.trim() || '') : '';

        if (wantsUrl && !baseUrl) {
            showError('Base URL is required for a custom endpoint.');
            return;
        }
        if (!key && !wantsUrl) {
            showError('Enter an API key.');
            return;
        }

        onSave(vendorSaveMessage(vendor, key, baseUrl));
        if (baseUrl) {
            overrides[vendor.id] = baseUrl;
        } else {
            delete overrides[vendor.id];
        }
        if (!configured.includes(vendor.id)) {
            configured = [...configured, vendor.id];
        }
        render();
    }

    function bindEvents() {
        dialog.querySelector('#settings-provider')?.addEventListener('change', (e) => {
            activeVendorId = e.target.value;
            render();
        });

        dialog.querySelector('#settings-save')?.addEventListener('click', save);

        dialog.querySelectorAll('.remove-provider').forEach(btn => {
            btn.addEventListener('click', () => {
                const provider = btn.dataset.provider;
                onDelete(provider);
                configured = configured.filter(name => name !== provider);
                delete overrides[provider];
                render();
            });
        });

        dialog.querySelector('.close-btn')?.addEventListener('click', () => {
            dialog.close();
            dialog.remove();
        });
    }

    render();

    dialog.addEventListener('close', () => dialog.remove());
    dialog.addEventListener('click', (e) => {
        if (e.target === dialog) {
            dialog.close();
            dialog.remove();
        }
    });

    document.body.appendChild(dialog);
    dialog.showModal();
}
