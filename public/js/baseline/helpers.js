export const STATUS_LABELS = {
    queued: 'Queued',
    fetching: 'Fetching',
    provider: 'Processing',
    validating: 'Validating',
    stored: 'Complete',
    failed: 'Error',
    cancelled: 'Cancelled',
    none: 'No run',
};

export const MANUAL_PDF_TAG = 'Manual PDF required';
export const MANUAL_PDF_REASON_NO_OA = 'no-open-access';
export const MANUAL_PDF_DETAILS = {
    [MANUAL_PDF_REASON_NO_OA]: 'No open-access PDF found',
    provider_empty: 'Provider returned no usable output (retry or upload)',
};

export function getBatchIdFromUrl(pathname = window.location.pathname) {
    const match = pathname.match(/^\/baseline\/(.+)$/);
    return match ? decodeURIComponent(match[1]) : null;
}

export function normalizeSequence(seq) {
    if (!seq) return '';
    return String(seq).replace(/\s+/g, '').toUpperCase();
}

export function normalizeDoiVersion(doi) {
    if (!doi) return null;
    return String(doi).replace(/\/v\d+$/i, '');
}

export function getCaseKey(caseItem) {
    return caseItem.id || '';
}

export function isProcessingStatus(status) {
    return ['queued', 'fetching', 'provider', 'validating'].includes(status);
}

export function normalizeDoiToUrl(doi) {
    if (!doi) return null;
    const cleaned = String(doi).trim();
    if (!cleaned) return null;
    if (/^https?:\/\//i.test(cleaned)) return cleaned;
    return `https://doi.org/${cleaned.replace(/^doi:\s*/i, '')}`;
}

export function isLocalPdfUrl(url) {
    return Boolean(url) && String(url).startsWith('upload://');
}

export function getStatusLabel(status) {
    if (!status) return STATUS_LABELS.none;
    return STATUS_LABELS[status] || status;
}

export function isProviderEmptyFailure(reason) {
    if (!reason) return false;
    const lower = String(reason).toLowerCase();
    return lower.includes('openai returned empty response') || lower.includes('stream has ended unexpectedly');
}

export function isNoSourceResolvedFailure(reason) {
    if (!reason) return false;
    const lower = String(reason).toLowerCase();
    return lower.includes('no source url resolved') || lower.includes('no pdf url resolved');
}

export function formatFailureReason(reason) {
    if (!reason) return null;
    const text = String(reason);
    const lower = text.toLowerCase();
    if (lower.includes('http 403')) {
        return {
            title: 'Access blocked (HTTP 403)',
            detail: 'Publisher blocked this URL. Try open-access search or upload a PDF.',
        };
    }
    if (lower.includes('no source url resolved') || lower.includes('no pdf url resolved')) {
        return {
            title: 'No source URL found',
            detail: 'We could not find a usable PDF/HTML source. Try open-access search or upload a PDF.',
        };
    }
    if (lower.includes('openai returned empty response') || lower.includes('stream has ended unexpectedly')) {
        return {
            title: 'Provider response was empty',
            detail: 'The provider returned no usable output. Retry or upload a PDF for better reliability.',
        };
    }
    if (lower.startsWith('provider error')) {
        return {
            title: 'Provider error',
            detail: text.replace(/^provider error:\s*/i, '') || 'The provider failed. Retry or upload a PDF.',
        };
    }
    return { title: text, detail: null };
}

export function mean(values) {
    if (!values.length) return null;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function median(values) {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 0) return (sorted[mid - 1] + sorted[mid]) / 2;
    return sorted[mid];
}

export function formatNumber(value, digits = 1) {
    if (value === null || value === undefined || Number.isNaN(value)) return 'n/a';
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(digits);
}

export function formatPercent(numerator, denominator, digits = 0) {
    if (!denominator) return 'n/a';
    const pct = (numerator / denominator) * 100;
    return `${pct.toFixed(digits)}%`;
}

export function incrementCount(map, value) {
    if (value === null || value === undefined || value === '') return;
    const key = String(value);
    map.set(key, (map.get(key) || 0) + 1);
}

export function getTopEntries(map, limit = 6) {
    return Array.from(map.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, limit)
        .map(([label, count]) => ({ label, count }));
}

export function bucketizeDeltas(values) {
    const buckets = [
        { label: '≤ -3', test: (v) => v <= -3 },
        { label: '-2', test: (v) => v === -2 },
        { label: '-1', test: (v) => v === -1 },
        { label: '0', test: (v) => v === 0 },
        { label: '1', test: (v) => v === 1 },
        { label: '2', test: (v) => v === 2 },
        { label: '≥ 3', test: (v) => v >= 3 },
    ];
    return buckets.map((bucket) => ({
        label: bucket.label,
        count: values.filter(bucket.test).length,
    }));
}
