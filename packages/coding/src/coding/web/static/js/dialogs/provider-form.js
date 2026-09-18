/**
 * Shared vendor picker helpers for the API key and settings dialogs.
 *
 * A vendor preset brings its own endpoint, so its form needs no Base URL
 * input. Everything else — the Custom entry, or a provider that only exists in
 * ~/.coding/models.json — does.
 */

export const CUSTOM_VENDOR_ID = '__custom__';

export const CUSTOM_VENDOR = {
    id: CUSTOM_VENDOR_ID,
    label: 'Custom (OpenAI-compatible)',
    baseUrl: '',
    apiKeyUrl: '',
};

/**
 * Vendors to offer: the server's presets, a Custom entry, plus the provider
 * that triggered the dialog when it is not a preset itself.
 */
export function getVendorChoices(vendors, extraProvider = '') {
    const choices = [...(vendors || [])];
    if (!choices.some(v => v.id === CUSTOM_VENDOR_ID)) {
        choices.push(CUSTOM_VENDOR);
    }
    if (extraProvider && !choices.some(v => v.id === extraProvider)) {
        choices.push({ id: extraProvider, label: extraProvider, baseUrl: '', apiKeyUrl: '' });
    }
    return choices;
}

/** Look up a vendor, falling back to Custom for unknown ids. */
export function findVendor(vendors, id) {
    return (vendors || []).find(v => v.id === id) || CUSTOM_VENDOR;
}

/** Presets are bound to their own endpoint, so they take no URL input. */
export function needsBaseUrl(vendor) {
    return !vendor.baseUrl;
}

/** Options markup for a vendor <select>. */
export function vendorOptionsHtml(vendors, selectedId) {
    return vendors.map(v => {
        const selected = v.id === selectedId ? ' selected' : '';
        return `<option value="${v.id}"${selected}>${v.label}</option>`;
    }).join('');
}

/**
 * Describe the endpoint a preset will use, plus where to get its API key.
 * Left empty for vendors that need a Base URL input instead.
 */
export function renderVendorEndpoint(el, vendor) {
    el.textContent = '';
    if (!vendor.baseUrl) return;

    el.append(`Endpoint: ${vendor.baseUrl}`);
    if (vendor.apiKeyUrl) {
        const link = document.createElement('a');
        link.href = vendor.apiKeyUrl;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.className = 'underline hover:text-foreground';
        link.textContent = 'Get an API key';
        el.append(' · ', link);
    }
}

/** Build the WebSocket message that saves this vendor's credentials. */
export function vendorSaveMessage(vendor, key, baseUrl) {
    if (vendor.id === CUSTOM_VENDOR_ID) {
        return { type: 'set_endpoint', key, baseUrl };
    }
    return { type: 'set_api_key', provider: vendor.id, key, baseUrl };
}
