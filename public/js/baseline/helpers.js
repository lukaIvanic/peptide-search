import {
    STATUS_LABELS,
    formatFailureReason,
    getStatusLabel,
    isNoSourceResolvedFailure,
    isProcessingStatus,
    isProviderEmptyFailure,
} from '../shared/formatting.js';

export { STATUS_LABELS, formatFailureReason, getStatusLabel, isNoSourceResolvedFailure, isProcessingStatus, isProviderEmptyFailure };

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
