export const STATUS_LABELS = {
  queued: 'Queued',
  fetching: 'Fetching',
  provider: 'Processing',
  validating: 'Validating',
  stored: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
  none: 'No run',
};

export const STATUS_CONFIG = {
  queued: { label: 'Queued', badge: 'sw-badge--queued', dot: 'sw-dot sw-dot--queued' },
  fetching: { label: 'Fetching', badge: 'sw-badge--processing', dot: 'sw-dot sw-dot--processing' },
  provider: { label: 'Processing', badge: 'sw-badge--processing', dot: 'sw-dot sw-dot--processing' },
  validating: { label: 'Validating', badge: 'sw-badge--processing', dot: 'sw-dot sw-dot--processing' },
  stored: { label: 'Done', badge: 'sw-badge--done', dot: 'sw-dot sw-dot--done' },
  failed: { label: 'Failed', badge: 'sw-badge--failed', dot: 'sw-dot sw-dot--failed' },
  cancelled: { label: 'Cancelled', badge: 'sw-badge--warn', dot: 'sw-dot sw-dot--neutral' },
};

export function getStatusLabel(status) {
  if (!status) return STATUS_LABELS.none;
  return STATUS_LABELS[status] || status;
}

export function getStatusConfig(status) {
  return STATUS_CONFIG[status] || { label: status || 'Unknown', badge: 'sw-badge--warn', dot: 'sw-dot sw-dot--neutral' };
}

export function isProcessingStatus(status) {
  return ['queued', 'fetching', 'provider', 'validating'].includes(status);
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
  if (isNoSourceResolvedFailure(text)) {
    return {
      title: 'No source URL found',
      detail: 'We could not find a usable PDF/HTML source. Try open-access search or upload a PDF.',
    };
  }
  if (isProviderEmptyFailure(text)) {
    return {
      title: 'Provider response was empty',
      detail: 'Retry or upload a PDF for better reliability.',
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
