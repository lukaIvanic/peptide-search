import * as api from './js/api.js?v=dev48';
import { $, el, fmt } from './js/renderers.js?v=dev46';

const STATUS_LABELS = {
	queued: 'Queued',
	fetching: 'Fetching',
	provider: 'Processing',
	validating: 'Validating',
	stored: 'Complete',
	failed: 'Error',
	cancelled: 'Cancelled',
	none: 'No run',
};
const MANUAL_PDF_TAG = 'Manual PDF required';
const MANUAL_PDF_REASON_NO_OA = 'no-open-access';
const MANUAL_PDF_DETAILS = {
	[MANUAL_PDF_REASON_NO_OA]: 'No open-access PDF found',
	provider_empty: 'Provider returned no usable output (retry or upload)',
};

const state = {
	cases: [],
	datasets: [],
	filterDataset: '',
	search: '',
	selectedId: null,
	provider: 'openai',
	pdfStatusFilter: 'all',
	resolvedSource: null,
	stagedFile: null,
	runPayloadCache: new Map(),
	comparisonCache: new Map(),
	manualPdfReasons: new Map(),
};

let sseConnection = null;
let analysisToken = 0;

function normalizeSequence(seq) {
	if (!seq) return '';
	return String(seq).replace(/\s+/g, '').toUpperCase();
}

function getCaseKey(caseItem) {
	return caseItem.id || '';
}

function updateStatus(message) {
	const status = $('#baselineStatus');
	if (status) status.textContent = message || '';
}

function isProcessingStatus(status) {
	return ['queued', 'fetching', 'provider', 'validating'].includes(status);
}

function ensureButtonLabel(button) {
	if (!button) return null;
	let label = button.querySelector('.sw-btn__label');
	if (!label) {
		label = el('span', 'sw-btn__label', button.textContent.trim());
		button.textContent = '';
		button.appendChild(label);
	}
	return label;
}

function setButtonLoading(button, isLoading, labelText = null) {
	if (!button) return;
	const label = ensureButtonLabel(button);
	if (isLoading) {
		if (!button.dataset.originalLabel) {
			button.dataset.originalLabel = label?.textContent || '';
		}
		button.disabled = true;
		button.classList.add('sw-btn--loading', 'cursor-not-allowed');
		if (!button.querySelector('.sw-spinner')) {
			const spinner = el('span', 'sw-spinner h-3 w-3 rounded-full');
			spinner.setAttribute('aria-hidden', 'true');
			button.prepend(spinner);
		}
		if (labelText !== null && label) {
			label.textContent = labelText;
		}
	} else {
		button.disabled = false;
		button.classList.remove('sw-btn--loading', 'cursor-not-allowed');
		const spinner = button.querySelector('.sw-spinner');
		if (spinner) spinner.remove();
		if (button.dataset.originalLabel && label) {
			label.textContent = button.dataset.originalLabel;
		}
		delete button.dataset.originalLabel;
	}
}

function createExternalLink(url, className = '') {
	const link = el('a', `underline text-cyan-500 hover:text-cyan-400 ${className}`.trim(), url);
	link.href = url;
	link.target = '_blank';
	link.rel = 'noopener';
	return link;
}

function normalizeDoiToUrl(doi) {
	if (!doi) return null;
	const cleaned = String(doi).trim();
	if (!cleaned) return null;
	if (/^https?:\/\//i.test(cleaned)) return cleaned;
	return `https://doi.org/${cleaned.replace(/^doi:\s*/i, '')}`;
}

function getPreferredPdfUrl(caseItem, runPayload = null) {
	return (
		runPayload?.run?.pdf_url ||
		runPayload?.paper?.pdf_url ||
		runPayload?.paper?.url ||
		caseItem?.pdf_url ||
		caseItem?.paper_url ||
		null
	);
}

function getStatusLabel(status) {
	if (!status) return STATUS_LABELS.none;
	return STATUS_LABELS[status] || status;
}

function isProviderEmptyFailure(reason) {
	if (!reason) return false;
	const lower = String(reason).toLowerCase();
	return lower.includes('openai returned empty response') || lower.includes('stream has ended unexpectedly');
}

function isNoSourceResolvedFailure(reason) {
	if (!reason) return false;
	const lower = String(reason).toLowerCase();
	return lower.includes('no source url resolved') || lower.includes('no pdf url resolved');
}

function formatFailureReason(reason) {
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

function getManualPdfStatus(caseItem, runPayload = null) {
	if (!caseItem) return null;
	const run = runPayload?.run || caseItem?.latest_run || null;
	if (run?.status === 'failed' && isProviderEmptyFailure(run.failure_reason)) {
		return {
			tag: MANUAL_PDF_TAG,
			detail: MANUAL_PDF_DETAILS.provider_empty,
			reason: 'provider-empty',
		};
	}
	if (run?.status === 'failed' && isNoSourceResolvedFailure(run.failure_reason)) {
		return {
			tag: MANUAL_PDF_TAG,
			detail: MANUAL_PDF_DETAILS[MANUAL_PDF_REASON_NO_OA],
			reason: MANUAL_PDF_REASON_NO_OA,
		};
	}
	const manualReason = caseItem.id ? state.manualPdfReasons.get(caseItem.id) : null;
	if (manualReason === MANUAL_PDF_REASON_NO_OA) {
		return {
			tag: MANUAL_PDF_TAG,
			detail: MANUAL_PDF_DETAILS[MANUAL_PDF_REASON_NO_OA],
			reason: manualReason,
		};
	}
	return null;
}

function buildRunIndicator(status) {
	const statusKey = status || 'none';
	let dotClass = 'sw-dot sw-dot--neutral';
	if (['queued', 'fetching', 'provider', 'validating'].includes(statusKey)) {
		dotClass = 'sw-dot sw-dot--processing';
	} else if (statusKey === 'stored') {
		dotClass = 'sw-dot sw-dot--done';
	} else if (statusKey === 'failed') {
		dotClass = 'sw-dot sw-dot--failed';
	} else if (statusKey === 'cancelled') {
		dotClass = 'sw-dot sw-dot--neutral';
	}
	const dot = el('span', `mt-1 ${dotClass}`);
	dot.setAttribute('title', statusKey === 'none' ? 'No run yet' : `Status: ${getStatusLabel(statusKey)}`);
	return dot;
}

function getExpectedEntityCount(caseItem) {
	const metadata = caseItem?.metadata || {};
	const candidates = [
		'expected_entities',
		'expected_entity_count',
		'entity_count',
		'entities_count',
		'num_entities',
		'total_entities',
	];
	for (const key of candidates) {
		const value = metadata[key];
		if (value === null || value === undefined || value === '') continue;
		const parsed = Number.parseInt(value, 10);
		if (Number.isFinite(parsed)) {
			return parsed;
		}
	}
	return null;
}

function getSourceFlags(caseItem) {
	const flags = [];
	if (caseItem?.pdf_url) flags.push('PDF URL');
	if (caseItem?.paper_url) flags.push('Paper URL');
	if (caseItem?.doi) flags.push('DOI');
	if (caseItem?.pubmed_id) flags.push('ID');
	return flags;
}

function getSourceHint(caseItem) {
	if (caseItem?.pdf_url) return { label: 'PDF URL', className: 'sw-chip--success' };
	if (caseItem?.paper_url) return { label: 'Paper URL', className: 'sw-chip--success' };
	if (caseItem?.doi) return { label: 'DOI', className: 'sw-chip--success' };
	if (caseItem?.pubmed_id) return { label: 'ID', className: 'sw-chip--success' };
	return { label: 'No source', className: 'sw-chip--warning' };
}

function buildComparison(caseItem, runPayload) {
	if (!caseItem || !runPayload) return null;
	const run = runPayload.run || {};
	if (run.status === 'failed') return null;
	const rawJson = run.raw_json || {};
	const entities = Array.isArray(rawJson.entities) ? rawJson.entities : [];
	const baselineSeq = normalizeSequence(caseItem.sequence);
	let matchIndex = -1;
	if (baselineSeq && entities.length) {
		entities.some((entity, index) => {
			const seq = entity?.peptide?.sequence_one_letter || '';
			if (normalizeSequence(seq) === baselineSeq) {
				matchIndex = index;
				return true;
			}
			return false;
		});
	}
	const baselineLabels = (caseItem.labels || []).map((label) => String(label).toLowerCase());
	const matchedLabels = matchIndex >= 0 ? entities[matchIndex]?.labels || [] : [];
	const matchedLabelSet = new Set(matchedLabels.map((label) => String(label).toLowerCase()));
	const overlapLabels = baselineLabels.filter((label) => matchedLabelSet.has(label));
	const overlapUnique = Array.from(new Set(overlapLabels));
	const baselineExpected = getExpectedEntityCount(caseItem);
	const extractedCount = entities.length;
	const entityDelta = baselineExpected === null ? null : extractedCount - baselineExpected;
	return {
		matchIndex,
		sequenceMatch: matchIndex >= 0,
		labelOverlapCount: overlapUnique.length,
		labelOverlapLabels: overlapUnique,
		baselineExpected,
		extractedCount,
		entityDelta,
	};
}

function renderSelectedCaseStrip(caseItem, runPayload) {
	const strip = $('#selectedCaseStrip');
	if (!strip) return;
	if (!caseItem) {
		strip.classList.add('hidden');
		return;
	}
	strip.classList.remove('hidden');
	const sequence = $('#selectedCaseSequence');
	if (sequence) sequence.textContent = caseItem.sequence || '(No sequence)';
	const dataset = $('#selectedCaseDataset');
	if (dataset) dataset.textContent = caseItem.dataset || 'Unknown dataset';
	const meta = $('#selectedCaseMeta');
	if (meta) {
		meta.innerHTML = '';
		meta.classList.add('flex', 'flex-wrap', 'gap-2');
		const doiUrl = normalizeDoiToUrl(caseItem.doi);
		const pdfUrl = getPreferredPdfUrl(caseItem, runPayload);
		const manualStatus = getManualPdfStatus(caseItem, runPayload);
		let resolveBtn = null;
		if (doiUrl) {
			meta.appendChild(createExternalLink(doiUrl, 'break-all max-w-full'));
		}
		if (pdfUrl) {
			meta.appendChild(createExternalLink(pdfUrl, 'break-all max-w-full'));
		} else {
			resolveBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
			resolveBtn.appendChild(el('span', 'sw-btn__label', 'Find PDF'));
			meta.appendChild(resolveBtn);
		}
		const metaLine = [caseItem.pubmed_id, caseItem.id].filter(Boolean).join(' · ');
		if (metaLine) {
			meta.appendChild(el('span', 'text-[10px] text-slate-500', metaLine));
		}
		if (manualStatus?.detail) {
			meta.appendChild(
				el('span', 'text-[10px] text-amber-600 break-words', manualStatus.detail),
			);
		}
		if (resolveBtn) {
			resolveBtn.addEventListener('click', async () => {
				setButtonLoading(resolveBtn, true, 'Finding...');
				try {
					updateStatus('Searching for open-access source...');
					const result = await api.resolveBaselineSource(caseItem.id);
					if (!result.found) {
						state.manualPdfReasons.set(caseItem.id, MANUAL_PDF_REASON_NO_OA);
						updateStatus('No open-access source found.');
						renderSelectedCaseStrip(caseItem, runPayload);
						renderCaseList({ skipAnalysis: true });
						return;
					}
					const resolvedUrl = result.pdf_url || result.url;
					caseItem.pdf_url = resolvedUrl || caseItem.pdf_url;
					state.manualPdfReasons.delete(caseItem.id);
					state.resolvedSource = {
						caseId: caseItem.id,
						url: resolvedUrl,
						label: result.pdf_url ? 'PDF URL' : 'Source URL',
					};
					updateStatus(`Found ${state.resolvedSource.label}.`);
					renderSelectedCaseStrip(caseItem, runPayload);
					renderExtractionDetail(runPayload, caseItem, null);
					renderCaseList({ skipAnalysis: true });
				} catch (err) {
					updateStatus(err.message || 'Failed to resolve source');
				} finally {
					setButtonLoading(resolveBtn, false);
				}
			});
		}
	}
}

function renderSummaryBlock(comparison) {
	const wrapper = el('div', 'sw-card sw-card--note p-3 text-[11px] text-slate-600');
	wrapper.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Summary'));
	const grid = el('div', 'mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2');
	const addMetric = (label, value) => {
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		row.appendChild(el('div', 'text-slate-700', value));
		grid.appendChild(row);
	};
	if (!comparison) {
		addMetric('Sequence match', 'n/a');
		addMetric('Label overlap', 'n/a');
		addMetric('Entity delta', 'n/a');
		wrapper.appendChild(grid);
		return wrapper;
	}
	addMetric('Sequence match', comparison.sequenceMatch ? 'Yes' : 'No');
	addMetric('Label overlap', `${comparison.labelOverlapCount}`);
	if (comparison.entityDelta === null) {
		addMetric('Entity delta', 'n/a');
	} else {
		const delta = comparison.entityDelta;
		const deltaText = `${delta > 0 ? '+' : ''}${delta}`;
		addMetric('Entity delta', deltaText);
	}
	wrapper.appendChild(grid);
	if (comparison.labelOverlapLabels?.length) {
		wrapper.appendChild(
			el('div', 'mt-2 text-[10px] text-slate-500', `Overlap: ${comparison.labelOverlapLabels.join(', ')}`),
		);
	}
	return wrapper;
}

function renderDatasetOptions() {
	const select = $('#datasetFilter');
	if (!select) return;
	select.innerHTML = '';
	const all = el('option', '', 'All datasets');
	all.value = '';
	select.appendChild(all);
	state.datasets.forEach((dataset) => {
		const option = el('option', '', `${dataset.label || dataset.id} (${dataset.count || 0})`);
		option.value = dataset.id;
		if (dataset.id === state.filterDataset) option.selected = true;
		select.appendChild(option);
	});
}

function renderCounts(filteredCount) {
	const total = state.cases.length;
	const baselineCount = $('#baselineCount');
	if (baselineCount) baselineCount.textContent = total ? `${total} cases` : '';
	const caseCount = $('#caseCount');
	if (caseCount) {
		const label = filteredCount === undefined ? total : filteredCount;
		caseCount.textContent = total ? `${label} shown` : '';
	}
}

function filterCases() {
	const query = state.search.trim().toLowerCase();
	return state.cases.filter((item) => {
		const haystack = [
			item.sequence,
			item.doi,
			item.pubmed_id,
			item.paper_url,
			item.id,
			item.dataset,
		]
			.filter(Boolean)
			.join(' ')
			.toLowerCase();
		if (query && !haystack.includes(query)) return false;
		const pdfFilter = state.pdfStatusFilter;
		if (pdfFilter === 'manual') {
			return Boolean(getManualPdfStatus(item));
		}
		if (pdfFilter === 'available') {
			const hasPdf = Boolean(getPreferredPdfUrl(item));
			return hasPdf && !getManualPdfStatus(item);
		}
		return true;
	});
}

function mean(values) {
	if (!values.length) return null;
	return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function median(values) {
	if (!values.length) return null;
	const sorted = [...values].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	if (sorted.length % 2 === 0) {
		return (sorted[mid - 1] + sorted[mid]) / 2;
	}
	return sorted[mid];
}

function formatNumber(value, digits = 1) {
	if (value === null || value === undefined || Number.isNaN(value)) return 'n/a';
	if (Number.isInteger(value)) return String(value);
	return value.toFixed(digits);
}

function formatPercent(numerator, denominator, digits = 0) {
	if (!denominator) return 'n/a';
	const pct = (numerator / denominator) * 100;
	return `${pct.toFixed(digits)}%`;
}

function incrementCount(map, value) {
	if (value === null || value === undefined || value === '') return;
	const key = String(value);
	map.set(key, (map.get(key) || 0) + 1);
}

function getTopEntries(map, limit = 6) {
	return Array.from(map.entries())
		.sort((a, b) => b[1] - a[1])
		.slice(0, limit)
		.map(([label, count]) => ({ label, count }));
}

function bucketizeDeltas(values) {
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

async function mapWithConcurrency(items, limit, worker) {
	const results = new Array(items.length);
	let nextIndex = 0;
	const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
		while (true) {
			const index = nextIndex++;
			if (index >= items.length) return;
			results[index] = await worker(items[index], index);
		}
	});
	await Promise.all(runners);
	return results;
}

async function fetchLatestRunPayload(caseItem) {
	if (!caseItem?.id) return null;
	const runId = caseItem.latest_run?.run_id || null;
	const cached = state.runPayloadCache.get(caseItem.id);
	if (cached && cached.runId === runId) {
		return cached.payload;
	}
	try {
		const payload = await api.getBaselineLatestRun(caseItem.id);
		state.runPayloadCache.set(caseItem.id, { runId, payload });
		return payload;
	} catch (err) {
		return null;
	}
}

function getComparisonCache(caseItem) {
	if (!caseItem?.id) return null;
	const runId = caseItem.latest_run?.run_id || null;
	const cached = state.comparisonCache.get(caseItem.id);
	if (!cached || cached.runId !== runId) return null;
	return cached.comparison;
}

function setComparisonCache(caseItem, comparison) {
	if (!caseItem?.id) return;
	const runId = caseItem.latest_run?.run_id || null;
	state.comparisonCache.set(caseItem.id, { runId, comparison });
}

function pruneComparisonCache(cases) {
	const activeIds = new Set(cases.map((item) => item.id));
	for (const key of state.comparisonCache.keys()) {
		if (!activeIds.has(key)) {
			state.comparisonCache.delete(key);
		}
	}
}

function pruneManualPdfReasons(cases) {
	const activeIds = new Set(cases.map((item) => item.id));
	for (const key of state.manualPdfReasons.keys()) {
		if (!activeIds.has(key)) {
			state.manualPdfReasons.delete(key);
		}
	}
}

function computeAggregateMetrics(successCases, runPayloads, comparisons = null) {
	let comparisonsCount = 0;
	let sequenceMatchCount = 0;
	const labelOverlapCounts = [];
	const deltaValues = [];
	const overlapLabelCounts = new Map();
	const tagCounts = {
		labels: new Map(),
		morphology: new Map(),
		methods: new Map(),
	};

	successCases.forEach((caseItem, index) => {
		const runPayload = runPayloads[index];
		if (!runPayload?.run) return;
		const comparison = comparisons ? comparisons[index] : buildComparison(caseItem, runPayload);
		if (!comparison) return;
		comparisonsCount += 1;
		if (comparison.sequenceMatch) sequenceMatchCount += 1;
		labelOverlapCounts.push(comparison.labelOverlapCount || 0);
		(comparison.labelOverlapLabels || []).forEach((label) => incrementCount(overlapLabelCounts, label));
		if (comparison.entityDelta !== null) deltaValues.push(comparison.entityDelta);

		const rawJson = runPayload.run.raw_json || runPayload.run.payload || {};
		const entities = Array.isArray(rawJson.entities) ? rawJson.entities : [];
		entities.forEach((entity) => {
			(entity.labels || []).forEach((label) => incrementCount(tagCounts.labels, label));
			(entity.morphology || []).forEach((label) => incrementCount(tagCounts.morphology, label));
			(entity.validation_methods || []).forEach((label) => incrementCount(tagCounts.methods, label));
		});
	});

	return {
		comparisonsCount,
		sequenceMatchCount,
		labelOverlapAvg: mean(labelOverlapCounts),
		labelOverlapMedian: median(labelOverlapCounts),
		overlapLabels: getTopEntries(overlapLabelCounts),
		entityDeltaAvg: mean(deltaValues),
		entityDeltaMedian: median(deltaValues),
		entityDeltaBuckets: bucketizeDeltas(deltaValues),
		topTags: {
			labels: getTopEntries(tagCounts.labels),
			morphology: getTopEntries(tagCounts.morphology),
			methods: getTopEntries(tagCounts.methods),
		},
	};
}

function renderAggregatePanel({ totalCount, statusCounts, metrics }) {
	const container = $('#baselineAnalysis');
	if (!container) return;
	container.innerHTML = '';

	if (!totalCount) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'No baseline cases in this filter.'));
		return;
	}

	const successCount = statusCounts.stored || 0;
	const failedCount = statusCounts.failed || 0;
	const pendingCount = (statusCounts.queued || 0) + (statusCounts.fetching || 0) + (statusCounts.provider || 0) + (statusCounts.validating || 0);
	const noneCount = statusCounts.none || 0;

	const summary = el('div', 'grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]');
	const addSummary = (label, value) => {
		const cell = el('div', 'flex flex-col gap-1');
		cell.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		cell.appendChild(el('div', 'text-slate-700', value));
		summary.appendChild(cell);
	};
	addSummary('Filtered cases', totalCount);
	addSummary('Successful', `${successCount} (${formatPercent(successCount, totalCount)})`);
	addSummary('Failed', failedCount);
	addSummary('Pending/none', pendingCount + noneCount);
	container.appendChild(summary);

	if (!metrics || metrics.comparisonsCount === 0) {
		container.appendChild(el('div', 'mt-2 text-xs text-slate-500', 'No successful runs to analyze yet.'));
		return;
	}

	const metricsGrid = el('div', 'mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]');
	const addMetric = (label, value) => {
		const cell = el('div', 'flex flex-col gap-1');
		cell.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		cell.appendChild(el('div', 'text-slate-700', value));
		metricsGrid.appendChild(cell);
	};
	addMetric('Sequence match rate', `${formatPercent(metrics.sequenceMatchCount, metrics.comparisonsCount)} (${metrics.sequenceMatchCount}/${metrics.comparisonsCount})`);
	addMetric('Label overlap avg/median', `${formatNumber(metrics.labelOverlapAvg)} / ${formatNumber(metrics.labelOverlapMedian)}`);
	addMetric('Entity delta avg/median', `${formatNumber(metrics.entityDeltaAvg)} / ${formatNumber(metrics.entityDeltaMedian)}`);
	container.appendChild(metricsGrid);

	const overlaps = el('div', 'mt-3');
	overlaps.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Top overlapping labels'));
	if (metrics.overlapLabels.length === 0) {
		overlaps.appendChild(el('div', 'mt-1 text-xs text-slate-500', 'n/a'));
	} else {
		const list = el('div', 'mt-1 flex flex-wrap gap-1');
		metrics.overlapLabels.forEach((entry) => {
			list.appendChild(el('span', 'sw-chip text-[10px] text-slate-500', `${entry.label} (${entry.count})`));
		});
		overlaps.appendChild(list);
	}
	container.appendChild(overlaps);

	const deltas = el('div', 'mt-3');
	deltas.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Entity delta distribution'));
	if (metrics.entityDeltaBuckets.every((bucket) => bucket.count === 0)) {
		deltas.appendChild(el('div', 'mt-1 text-xs text-slate-500', 'n/a'));
	} else {
		const list = el('div', 'mt-1 flex flex-wrap gap-1');
		metrics.entityDeltaBuckets.forEach((bucket) => {
			list.appendChild(el('span', 'sw-chip text-[10px] text-slate-500', `${bucket.label}: ${bucket.count}`));
		});
		deltas.appendChild(list);
	}
	container.appendChild(deltas);

	const tags = el('div', 'mt-3 grid grid-cols-1 md:grid-cols-3 gap-2 text-[11px]');
	const addTags = (label, items) => {
		const col = el('div', 'flex flex-col gap-1');
		col.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		if (!items.length) {
			col.appendChild(el('div', 'text-slate-500', 'n/a'));
		} else {
			const list = el('div', 'flex flex-wrap gap-1');
			items.forEach((item) => {
				list.appendChild(el('span', 'sw-chip text-[10px] text-slate-500', `${item.label} (${item.count})`));
			});
			col.appendChild(list);
		}
		tags.appendChild(col);
	};
	addTags('Top labels', metrics.topTags.labels);
	addTags('Top morphology', metrics.topTags.morphology);
	addTags('Top methods', metrics.topTags.methods);
	container.appendChild(tags);
}

async function updateAggregateAnalysis(cases = filterCases()) {
	const container = $('#baselineAnalysis');
	if (!container) return;
	const totalCount = cases.length;
	const statusCounts = cases.reduce((counts, item) => {
		const status = item.latest_run?.status || 'none';
		counts[status] = (counts[status] || 0) + 1;
		return counts;
	}, {});
	const successCases = cases.filter((item) => item.latest_run?.status === 'stored');
	pruneComparisonCache(cases);
	cases.forEach((item) => {
		if (item.latest_run?.status !== 'stored') {
			state.comparisonCache.delete(item.id);
		}
	});

	const hint = $('#analysisHint');
	if (hint) {
		const successCount = statusCounts.stored || 0;
		hint.textContent = totalCount ? `${successCount} successful of ${totalCount} filtered` : 'No filtered cases';
	}

	container.innerHTML = '';
	if (!totalCount) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'No baseline cases in this filter.'));
		return;
	}
	container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'Computing analysis...'));

	if (!successCases.length) {
		renderAggregatePanel({ totalCount, statusCounts, metrics: null });
		return;
	}

	const token = ++analysisToken;
	const runPayloads = await mapWithConcurrency(successCases, 6, fetchLatestRunPayload);
	if (token !== analysisToken) return;
	const comparisons = successCases.map((caseItem, index) => {
		const runPayload = runPayloads[index];
		if (!runPayload?.run) return null;
		const comparison = buildComparison(caseItem, runPayload);
		if (comparison) {
			setComparisonCache(caseItem, comparison);
		}
		return comparison;
	});
	const metrics = computeAggregateMetrics(successCases, runPayloads, comparisons);
	renderAggregatePanel({ totalCount, statusCounts, metrics });
	renderCaseList({ skipAnalysis: true });
}

function renderCaseList({ skipAnalysis = false } = {}) {
	const container = $('#baselineList');
	container.innerHTML = '';
	const cases = filterCases();
	if (!cases.length) {
		container.appendChild(el('div', 'sw-empty py-6 text-sm text-slate-500 text-center', 'No baseline cases found.'));
		return;
	}

	cases.forEach((item) => {
		const isSelected = state.selectedId === item.id;
		const row = el('div', `py-3 px-3 flex items-start gap-3 sw-row ${isSelected ? 'sw-row--selected' : ''}`);
		row.setAttribute('role', 'button');
		row.setAttribute('tabindex', '0');

		const content = el('div', 'flex-1 min-w-0');
		const titleRow = el('div', 'flex items-start gap-2');
		const latest = item.latest_run;
		const statusKey = latest?.status || 'none';
		titleRow.appendChild(buildRunIndicator(statusKey));
		titleRow.appendChild(el('div', 'text-xs font-medium text-slate-900 flex-1 break-words', item.sequence || '(No sequence)'));

		content.appendChild(titleRow);

		const metaRow = el('div', 'mt-1 flex flex-wrap items-center gap-2');
		const manualStatus = getManualPdfStatus(item);
		if (item.dataset) {
			metaRow.appendChild(el('span', 'sw-chip text-[9px] text-slate-500', item.dataset));
		}
	const sourceHint = getSourceHint(item);
	if (sourceHint) {
		metaRow.appendChild(el('span', `sw-chip ${sourceHint.className} text-[9px]`, sourceHint.label));
	}
		if (manualStatus?.tag) {
			metaRow.appendChild(el('span', 'sw-chip sw-chip--warning text-[9px]', manualStatus.tag));
		}
		const metaLine = [item.doi || item.pubmed_id || item.id].filter(Boolean).join(' · ');
		if (metaLine) {
			metaRow.appendChild(el('div', 'text-[10px] text-slate-500 break-words', metaLine));
		}
		if (metaRow.childNodes.length) {
			content.appendChild(metaRow);
		}

		if (latest?.status === 'stored') {
			const tagRow = el('div', 'mt-1 flex flex-wrap items-center gap-2');
			const comparison = getComparisonCache(item);
			if (!comparison) {
				tagRow.appendChild(el('span', 'sw-chip sw-chip--info text-[9px]', 'Analyzing...'));
			} else {
				const seqLabel = comparison.sequenceMatch ? 'Seq: Match' : 'Seq: No match';
				const seqClass = comparison.sequenceMatch ? 'sw-chip--success' : 'sw-chip--warning';
				tagRow.appendChild(el('span', `sw-chip ${seqClass} text-[9px]`, seqLabel));
				tagRow.appendChild(el('span', 'sw-chip text-[9px]', `Overlap: ${comparison.labelOverlapCount ?? 0}`));
				if (comparison.entityDelta !== null && comparison.entityDelta !== undefined) {
					const delta = comparison.entityDelta;
					const deltaText = `${delta > 0 ? '+' : ''}${delta}`;
					tagRow.appendChild(el('span', 'sw-chip text-[9px]', `Δ entities: ${deltaText}`));
				}
			}
			content.appendChild(tagRow);
		}

		if (latest?.status === 'failed' && latest.failure_reason) {
			const friendly = formatFailureReason(latest.failure_reason);
			const message = friendly?.title || latest.failure_reason;
			content.appendChild(el('div', 'mt-1 text-[10px] text-red-500 break-words', message));
		}

		row.appendChild(content);
		row.addEventListener('click', () => selectCase(item.id));
		row.addEventListener('keydown', (event) => {
			if (event.key === 'Enter' || event.key === ' ') {
				event.preventDefault();
				selectCase(item.id);
			}
		});
		container.appendChild(row);
	});

	renderCounts(cases.length);
	if (!skipAnalysis) {
		updateAggregateAnalysis(cases);
	}
}

function renderBaselineDetail(caseItem, comparison, runPayload = null) {
	const container = $('#baselineDetail');
	container.innerHTML = '';
	if (!caseItem) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'Select a case from the list to compare against the latest run.'));
		return;
	}

	const headerRow = el('div', 'flex flex-wrap items-center gap-2');
	headerRow.appendChild(el('div', 'text-sm font-medium text-slate-900', caseItem.sequence || '(No sequence)'));
	const matchLabel = comparison
		? comparison.sequenceMatch ? 'Match' : 'No match'
		: 'Not compared';
	const matchClass = comparison
		? comparison.sequenceMatch ? 'sw-chip--success' : 'sw-chip--warning'
		: 'sw-chip--info';
	headerRow.appendChild(el('span', `sw-chip ${matchClass} text-[10px]`, matchLabel));
	container.appendChild(headerRow);
	const tags = el('div', 'flex flex-wrap gap-2 text-[10px] text-slate-500');
	(caseItem.labels || []).forEach((label) => tags.appendChild(el('span', 'sw-chip', label)));
	if (caseItem.dataset) tags.appendChild(el('span', 'sw-chip', caseItem.dataset));
	container.appendChild(tags);

	const meta = el('div', 'grid grid-cols-1 gap-2 text-[11px]');
	const addRow = (label, value, allowEmpty = false) => {
		if (!allowEmpty && (value === null || value === undefined || value === '')) return;
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		row.appendChild(el('div', 'text-slate-700 break-words', value || 'Not provided'));
		meta.appendChild(row);
	};
	const addLinkRow = (label, url) => {
		if (!url) return;
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		row.appendChild(createExternalLink(url, 'break-all max-w-full'));
		meta.appendChild(row);
	};

	addRow('DOI', caseItem.doi);
	addRow('PubMed/Patent', caseItem.pubmed_id);
	addRow('N-terminus', caseItem.n_terminal);
	addRow('C-terminus', caseItem.c_terminal);
	const preferredPdfUrl = getPreferredPdfUrl(caseItem, runPayload);
	addLinkRow('PDF link', preferredPdfUrl);
	if (caseItem.paper_url && caseItem.paper_url !== preferredPdfUrl) {
		addLinkRow('Paper link', caseItem.paper_url);
	}
	const sourceFlags = getSourceFlags(caseItem);
	addRow('Source fields', sourceFlags.length ? sourceFlags.join(', ') : 'None', true);
	addRow('Expected entities', getExpectedEntityCount(caseItem), true);
	container.appendChild(meta);

	if (caseItem.metadata && Object.keys(caseItem.metadata).length) {
		const metaBlock = el('div', 'sw-card sw-card--note p-3 text-[11px] text-slate-600');
		metaBlock.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Dataset metadata'));
		Object.entries(caseItem.metadata).forEach(([key, value]) => {
			if (value === null || value === undefined || value === '') return;
			const row = el('div', 'mt-1');
			row.appendChild(el('span', 'text-slate-500', `${key}: `));
			row.appendChild(el('span', 'text-slate-700 break-words', String(value)));
			metaBlock.appendChild(row);
		});
		container.appendChild(metaBlock);
	}
}

function renderEntityDetails(entity) {
	const rows = [];
	const addRow = (label, value) => {
		if (value === undefined || value === null || value === '') return;
		if (Array.isArray(value) && value.length === 0) return;
		rows.push({ label, value });
	};

	if (entity.type === 'peptide' && entity.peptide) {
		addRow('Sequence (1-letter)', entity.peptide.sequence_one_letter);
		addRow('Sequence (3-letter)', entity.peptide.sequence_three_letter);
		addRow('N-terminal mod', entity.peptide.n_terminal_mod);
		addRow('C-terminal mod', entity.peptide.c_terminal_mod);
		if (entity.peptide.is_hydrogel !== undefined && entity.peptide.is_hydrogel !== null) {
			addRow('Hydrogel', entity.peptide.is_hydrogel ? 'Yes' : 'No');
		}
	}

	if (entity.type === 'molecule' && entity.molecule) {
		addRow('Chemical formula', entity.molecule.chemical_formula);
		addRow('SMILES', entity.molecule.smiles);
		addRow('InChI', entity.molecule.inchi);
	}

	addRow('Labels', entity.labels);
	addRow('Morphology', entity.morphology);
	addRow('Validation methods', entity.validation_methods);
	addRow('Reported characteristics', entity.reported_characteristics);
	addRow('Process protocol', entity.process_protocol);

	if (entity.conditions) {
		const conditions = [];
		if (entity.conditions.ph !== null && entity.conditions.ph !== undefined) {
			conditions.push(`pH ${entity.conditions.ph}`);
		}
		if (entity.conditions.concentration !== null && entity.conditions.concentration !== undefined) {
			const unit = entity.conditions.concentration_units ? ` ${entity.conditions.concentration_units}` : '';
			conditions.push(`Concentration ${entity.conditions.concentration}${unit}`);
		}
		if (entity.conditions.temperature_c !== null && entity.conditions.temperature_c !== undefined) {
			conditions.push(`Temperature ${entity.conditions.temperature_c} °C`);
		}
		if (conditions.length) addRow('Conditions', conditions);
	}

	if (entity.thresholds) {
		const thresholds = [];
		if (entity.thresholds.cac !== null && entity.thresholds.cac !== undefined) thresholds.push(`CAC ${entity.thresholds.cac}`);
		if (entity.thresholds.cgc !== null && entity.thresholds.cgc !== undefined) thresholds.push(`CGC ${entity.thresholds.cgc}`);
		if (entity.thresholds.mgc !== null && entity.thresholds.mgc !== undefined) thresholds.push(`MGC ${entity.thresholds.mgc}`);
		if (thresholds.length) addRow('Thresholds', thresholds);
	}

	if (!rows.length) {
		return el('div', 'mt-2 text-xs text-slate-400', 'No structured fields reported.');
	}

	const wrapper = el('div', 'mt-3 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs');
	rows.forEach(({ label, value }) => {
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		const text = Array.isArray(value) ? value.join(', ') : String(value);
		row.appendChild(el('div', 'text-slate-700 break-words', text));
		wrapper.appendChild(row);
	});
	return wrapper;
}

function renderEntities(rawJson, matchIndex) {
	const container = el('div', 'space-y-3');
	if (!rawJson?.entities?.length) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500 p-3', 'No entities found.'));
		return container;
	}
	rawJson.entities.forEach((entity, index) => {
		const isMatch = index === matchIndex;
		const card = el('div', `sw-card p-3 ${isMatch ? 'sw-card--success' : ''}`);
		card.appendChild(el('div', 'sw-kicker text-[10px] text-slate-500', `Entity ${index + 1}`));
		card.appendChild(el('div', 'text-sm font-medium text-slate-900 mt-1', entity.type || 'entity'));
		if (isMatch) {
			card.appendChild(el('div', 'text-[10px] text-emerald-600 mt-1', 'Matched sequence'));
		}
		if (entity.type === 'peptide' && entity.peptide) {
			const peptide = entity.peptide;
			const seq = peptide.sequence_one_letter || peptide.sequence_three_letter;
			if (seq) card.appendChild(el('div', 'text-sm text-slate-900 mt-1', seq));
		}
		if (entity.type === 'molecule' && entity.molecule) {
			const molecule = entity.molecule;
			const id = molecule.chemical_formula || molecule.smiles || molecule.inchi;
			if (id) card.appendChild(el('div', 'text-sm text-slate-900 mt-1', id));
		}
		const details = renderEntityDetails(entity);
		if (details) card.appendChild(details);
		container.appendChild(card);
	});
	return container;
}

function renderExtractionDetail(runPayload, caseItem, comparison) {
	const container = $('#extractionDetail');
	container.innerHTML = '';
	if (!caseItem) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'Select a case from the list to compare against the latest run.'));
		return;
	}
	if (!runPayload) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'No extraction run yet.'));
		container.appendChild(renderBaselineFixPanel(caseItem, null));
		return;
	}

	const run = runPayload.run || {};
	const paper = runPayload.paper || {};
	const header = el('div', 'space-y-1 text-xs text-slate-500');
	header.appendChild(el('div', '', `Run status: ${getStatusLabel(run.status || 'none')}`));
	if (run.created_at) {
		header.appendChild(el('div', '', new Date(run.created_at).toLocaleString()));
	}
	if (run.model_provider || run.model_name) {
		header.appendChild(el('div', '', `${fmt(run.model_provider)} ${fmt(run.model_name)}`.trim()));
	}
	if (paper?.doi) {
		header.appendChild(el('div', '', `DOI: ${paper.doi}`));
	}
	const headerPdfUrl = getPreferredPdfUrl(caseItem, runPayload);
	if (headerPdfUrl) {
		const linkRow = el('div', 'break-all max-w-full');
		linkRow.appendChild(el('span', '', 'PDF link: '));
		linkRow.appendChild(createExternalLink(headerPdfUrl));
		header.appendChild(linkRow);
	}
	container.appendChild(header);

	const paperId = paper?.id || run.paper_id;
	if (paperId && run.status === 'stored') {
		const actionsRow = el('div', 'mt-2 flex flex-wrap items-center gap-2');
		const forceBtn = el('button', 'sw-btn sw-btn--sm sw-btn--primary');
		forceBtn.appendChild(el('span', 'sw-btn__label', 'Force Re-extract'));
		forceBtn.addEventListener('click', async () => {
			setButtonLoading(forceBtn, true, 'Re-extracting...');
			try {
				updateStatus('Forcing re-extract...');
				await api.forceReextract(paperId, state.provider);
				await loadCaseDetails(caseItem.id);
				await loadCases();
				updateStatus('Re-extract queued.');
			} catch (err) {
				updateStatus(err.message || 'Failed to force re-extract');
			} finally {
				setButtonLoading(forceBtn, false);
			}
		});
		actionsRow.appendChild(forceBtn);
		const uploadBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
		uploadBtn.appendChild(el('span', 'sw-btn__label', 'Upload PDF'));
		const fileInput = el('input', 'hidden');
		fileInput.type = 'file';
		fileInput.accept = '.pdf';
		uploadBtn.addEventListener('click', () => fileInput.click());
		fileInput.addEventListener('change', async () => {
			const file = fileInput.files && fileInput.files[0];
			if (!file) return;
			setButtonLoading(uploadBtn, true, 'Uploading...');
			try {
				updateStatus('Uploading PDF and queuing extraction...');
				await api.uploadBaselinePdf(caseItem.id, file, state.provider);
				await loadCaseDetails(caseItem.id);
				await loadCases();
				updateStatus('PDF uploaded. Extraction queued.');
			} catch (err) {
				updateStatus(err.message || 'Failed to upload PDF');
			} finally {
				setButtonLoading(uploadBtn, false);
				fileInput.value = '';
			}
		});
		actionsRow.appendChild(uploadBtn);
		actionsRow.appendChild(fileInput);
		container.appendChild(actionsRow);
	}

	if (isProcessingStatus(run.status)) {
		const processing = el('div', 'sw-card sw-card--note p-3 text-xs text-slate-600 flex items-center gap-2');
		processing.appendChild(el('span', 'sw-spinner h-3 w-3 rounded-full'));
		processing.appendChild(el('div', '', `Processing: ${getStatusLabel(run.status)}`));
		container.appendChild(processing);
	}

	if (run.status === 'failed') {
		const errorBox = el('div', 'sw-card sw-card--error p-3 text-xs text-slate-600');
		const friendly = formatFailureReason(run.failure_reason);
		if (friendly) {
			errorBox.appendChild(el('div', 'text-slate-700 font-medium', friendly.title));
			if (friendly.detail) {
				errorBox.appendChild(el('div', 'mt-1 text-[11px] text-slate-500', friendly.detail));
			}
		} else {
			errorBox.textContent = run.failure_reason || 'Unknown failure';
		}
		container.appendChild(errorBox);
		container.appendChild(renderBaselineFixPanel(caseItem, runPayload));
		return;
	}

	const comparisonInfo = comparison || buildComparison(caseItem, runPayload);
	container.appendChild(renderSummaryBlock(comparisonInfo));

	const rawJson = run.raw_json || {};
	const matchIndex = comparisonInfo?.matchIndex ?? -1;
	container.appendChild(renderEntities(rawJson, matchIndex));
}

function renderBaselineFixPanel(caseItem, runPayload) {
	const panel = el('div', 'sw-card sw-card--note p-3 text-[11px] text-slate-600');
	panel.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Fix this failure'));

	const resolvedSource =
		state.resolvedSource && state.resolvedSource.caseId === caseItem.id ? state.resolvedSource : null;
	const hasHeaderPdf = Boolean(getPreferredPdfUrl(caseItem, runPayload));
	const stagedFile = state.stagedFile && state.stagedFile.caseId === caseItem.id ? state.stagedFile : null;

	const actions = el('div', 'mt-2 flex flex-wrap items-center gap-2');
	const retryBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
	retryBtn.appendChild(el('span', 'sw-btn__label', 'Retry same source'));
	const resolveBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
	resolveBtn.appendChild(el('span', 'sw-btn__label', 'Find open-access PDF'));

	const fileInput = el('input', 'hidden');
	fileInput.type = 'file';
	fileInput.accept = '.pdf';
	const uploadBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
	uploadBtn.appendChild(el('span', 'sw-btn__label', 'Upload PDF'));

	let runNowBtn = null;
	const actionButtons = [retryBtn, resolveBtn, uploadBtn];
	const setButtonsDisabled = (disabled) => {
		actionButtons.forEach((btn) => {
			if (!btn) return;
			if (disabled) {
				btn.disabled = true;
				if (!btn.classList.contains('sw-btn--primary')) {
					btn.classList.add('opacity-60');
				}
				btn.classList.add('cursor-not-allowed');
			} else if (!btn.classList.contains('sw-btn--loading')) {
				btn.disabled = false;
				btn.classList.remove('opacity-60', 'cursor-not-allowed');
			}
		});
	};

	retryBtn.addEventListener('click', async () => {
		setButtonsDisabled(true);
		setButtonLoading(retryBtn, true, 'Retrying...');
		try {
			updateStatus('Re-queueing baseline case...');
			await api.retryBaselineCase(caseItem.id, { provider: state.provider });
			state.resolvedSource = null;
			state.stagedFile = null;
			await loadCaseDetails(caseItem.id);
			await loadCases();
			updateStatus('Baseline case re-queued.');
		} catch (err) {
			updateStatus(err.message || 'Failed to retry baseline case');
		} finally {
			setButtonLoading(retryBtn, false);
			setButtonsDisabled(false);
		}
	});
	actions.appendChild(retryBtn);

	resolveBtn.addEventListener('click', async () => {
		setButtonsDisabled(true);
		setButtonLoading(resolveBtn, true, 'Searching...');
		try {
			updateStatus('Searching for open-access source...');
			const result = await api.resolveBaselineSource(caseItem.id);
			if (!result.found) {
				state.resolvedSource = null;
				state.stagedFile = null;
				state.manualPdfReasons.set(caseItem.id, MANUAL_PDF_REASON_NO_OA);
				updateStatus('No open-access source found.');
				renderCaseList({ skipAnalysis: true });
				return;
			}
			state.resolvedSource = {
				caseId: caseItem.id,
				url: result.pdf_url || result.url,
				label: result.pdf_url ? 'PDF URL' : 'Source URL',
			};
			state.manualPdfReasons.delete(caseItem.id);
			state.stagedFile = null;
			updateStatus(`Found ${state.resolvedSource.label}. Review and run.`);
			renderExtractionDetail(runPayload, caseItem, null);
			renderCaseList({ skipAnalysis: true });
		} catch (err) {
			updateStatus(err.message || 'Failed to resolve source');
		} finally {
			setButtonLoading(resolveBtn, false);
			setButtonsDisabled(false);
		}
	});
	if (!hasHeaderPdf) {
		actions.appendChild(resolveBtn);
	}

	uploadBtn.addEventListener('click', () => fileInput.click());
	fileInput.addEventListener('change', () => {
		const file = fileInput.files && fileInput.files[0];
		if (!file) return;
		state.stagedFile = { caseId: caseItem.id, file, name: file.name };
		state.resolvedSource = null;
		state.manualPdfReasons.delete(caseItem.id);
		fileInput.value = '';
		updateStatus(`Selected PDF: ${file.name}. Click Run now.`);
		renderExtractionDetail(runPayload, caseItem, null);
		renderCaseList({ skipAnalysis: true });
	});
	panel.appendChild(fileInput);
	actions.appendChild(uploadBtn);

	panel.appendChild(actions);

	if (resolvedSource?.url) {
		const resolvedRow = el('div', 'mt-2 text-[10px] text-slate-500 break-all max-w-full');
		resolvedRow.appendChild(el('span', '', `Resolved ${resolvedSource.label}: `));
		resolvedRow.appendChild(createExternalLink(resolvedSource.url));
		panel.appendChild(resolvedRow);
	}

	if (stagedFile?.name) {
		const fileRow = el('div', 'mt-2 text-[10px] text-slate-500');
		fileRow.textContent = `Selected PDF: ${stagedFile.name}`;
		panel.appendChild(fileRow);
	}

	if ((resolvedSource && resolvedSource.url) || stagedFile) {
		runNowBtn = el('button', 'sw-btn sw-btn--sm sw-btn--primary mt-2');
		runNowBtn.appendChild(el('span', 'sw-btn__label', 'Run now'));
		actionButtons.push(runNowBtn);
		runNowBtn.addEventListener('click', async () => {
			const sourceUrl = resolvedSource?.url;
			const staged = state.stagedFile && state.stagedFile.caseId === caseItem.id ? state.stagedFile : null;
			if (!sourceUrl && !staged) {
				updateStatus('No PDF or source URL selected.');
				return;
			}
			setButtonsDisabled(true);
			setButtonLoading(runNowBtn, true, 'Extracting...');
			try {
				if (staged) {
					updateStatus('Uploading PDF and starting extraction...');
					await api.uploadBaselinePdf(caseItem.id, staged.file, state.provider);
					state.manualPdfReasons.delete(caseItem.id);
				} else {
					updateStatus('Starting extraction with resolved source...');
					await api.retryBaselineCase(caseItem.id, { provider: state.provider, source_url: sourceUrl });
				}
				state.resolvedSource = null;
				state.stagedFile = null;
				await loadCaseDetails(caseItem.id);
				await loadCases();
				updateStatus(staged ? 'PDF uploaded and extraction started.' : 'Baseline case re-queued.');
			} catch (err) {
				updateStatus(err.message || 'Failed to start extraction');
			} finally {
				setButtonLoading(runNowBtn, false);
				setButtonsDisabled(false);
			}
		});
		panel.appendChild(runNowBtn);
	}

	return panel;
}

async function loadCaseDetails(caseId) {
	try {
		const caseData = await api.getBaselineCase(caseId);
		if (caseData.latest_run) {
			const runPayload = await api.getBaselineLatestRun(caseId);
			const comparison = buildComparison(caseData, runPayload);
			renderBaselineDetail(caseData, comparison, runPayload);
			renderExtractionDetail(runPayload, caseData, comparison);
			renderSelectedCaseStrip(caseData, runPayload);
			$('#comparisonHint').textContent = `Case ${caseData.id}`;
		} else {
			renderBaselineDetail(caseData, null, null);
			renderExtractionDetail(null, caseData, null);
			renderSelectedCaseStrip(caseData, null);
			$('#comparisonHint').textContent = `Case ${caseData.id}`;
		}
	} catch (err) {
		renderBaselineDetail(null, null, null);
		renderExtractionDetail(null, null, null);
		renderSelectedCaseStrip(null, null);
		$('#comparisonHint').textContent = 'Select a baseline case';
		updateStatus(err.message || 'Failed to load case');
	}
}

async function selectCase(caseId) {
	state.selectedId = caseId;
	state.resolvedSource = null;
	state.stagedFile = null;
	renderCaseList();
	await loadCaseDetails(caseId);
}

async function loadCases() {
	try {
		updateStatus('Loading baseline cases...');
		const data = await api.getBaselineCases(state.filterDataset);
		state.cases = data.cases || [];
		state.datasets = data.datasets || [];
		state.cases.forEach((item) => {
			if (item?.id && item?.pdf_url) {
				state.manualPdfReasons.delete(item.id);
			}
		});
		pruneManualPdfReasons(state.cases);
		renderDatasetOptions();
		renderCaseList();
		if (state.selectedId) {
			const stillExists = state.cases.some((item) => item.id === state.selectedId);
			if (!stillExists) {
				state.selectedId = null;
				state.resolvedSource = null;
				state.stagedFile = null;
				renderBaselineDetail(null, null);
				renderExtractionDetail(null, null, null);
				renderSelectedCaseStrip(null, null);
				$('#comparisonHint').textContent = 'Select a baseline case';
			}
		}
		updateStatus('');
	} catch (err) {
		updateStatus(err.message || 'Failed to load baseline cases');
	}
}

async function enqueueBaselineRuns() {
	const runButton = $('#runBaselineBtn');
	if (runButton) {
		runButton.disabled = true;
		runButton.classList.add('opacity-60', 'cursor-not-allowed');
	}
	try {
		const dataset = state.filterDataset || null;
		const provider = state.provider || 'openai';
		updateStatus(dataset ? `Enqueuing ${dataset} (${provider})...` : `Enqueuing baseline (${provider})...`);
		const response = await api.enqueueBaselineAll(provider, null, dataset, false);
		const enqueued = response?.enqueued ?? 0;
		const skipped = response?.skipped ?? 0;
		const total = response?.total ?? (enqueued + skipped);
		const summary = `Enqueued ${enqueued} of ${total} cases${skipped ? ` (${skipped} skipped)` : ''}.`;
		updateStatus(summary);
		await loadCases();
	} catch (err) {
		updateStatus(err.message || 'Failed to enqueue baseline benchmark');
	} finally {
		if (runButton) {
			runButton.disabled = false;
			runButton.classList.remove('opacity-60', 'cursor-not-allowed');
		}
	}
}

async function resolveBaselineSourcesBulk() {
	const resolveButton = $('#resolveBaselineBtn');
	const cases = filterCases();
	if (!cases.length) {
		updateStatus('No baseline cases in the current filter.');
		return;
	}
	const targets = cases.filter((item) => !item?.pdf_url);
	const skipped = cases.length - targets.length;
	if (!targets.length) {
		updateStatus('All filtered cases already have PDF links.');
		return;
	}
	if (resolveButton) {
		setButtonLoading(resolveButton, true, 'Finding PDFs...');
	}
	let completed = 0;
	let found = 0;
	let notFound = 0;
	let errors = 0;
	const total = targets.length;
	const reportProgress = () => {
		updateStatus(`Resolving PDFs: ${completed}/${total}...`);
	};
	reportProgress();
	try {
		await mapWithConcurrency(targets, 6, async (caseItem) => {
			try {
				const result = await api.resolveBaselineSource(caseItem.id);
				if (result?.found) {
					const resolvedUrl = result.pdf_url || result.url;
					if (resolvedUrl) {
						caseItem.pdf_url = resolvedUrl;
					}
					state.manualPdfReasons.delete(caseItem.id);
					found += 1;
				} else {
					state.manualPdfReasons.set(caseItem.id, MANUAL_PDF_REASON_NO_OA);
					notFound += 1;
				}
			} catch (err) {
				state.manualPdfReasons.set(caseItem.id, MANUAL_PDF_REASON_NO_OA);
				errors += 1;
			} finally {
				completed += 1;
				reportProgress();
			}
		});
		const failures = notFound + errors;
		const summaryParts = [`Resolved ${found} of ${total}`];
		if (failures) summaryParts.push(`${failures} need manual PDF`);
		if (skipped) summaryParts.push(`${skipped} skipped`);
		updateStatus(`${summaryParts.join('. ')}.`);
		renderCaseList({ skipAnalysis: true });
		if (state.selectedId) {
			await loadCaseDetails(state.selectedId);
		}
	} finally {
		if (resolveButton) {
			setButtonLoading(resolveButton, false);
		}
	}
}

function connectSSE() {
	if (sseConnection) {
		sseConnection.close();
	}
	sseConnection = api.createSSEConnection((message) => {
		if (message.event !== 'run_status') return;
		const data = message.data || {};
		const caseIds = Array.isArray(data.baseline_case_ids) && data.baseline_case_ids.length
			? data.baseline_case_ids
			: (data.baseline_case_id ? [data.baseline_case_id] : []);
		if (!caseIds.length) return;
		let updated = false;
		let selectedUpdated = false;
		caseIds.forEach((caseId) => {
			const caseItem = state.cases.find((item) => item.id === caseId);
			if (!caseItem) return;
			updated = true;
			state.runPayloadCache.delete(caseId);
			state.comparisonCache.delete(caseId);
			caseItem.latest_run = {
				run_id: data.run_id,
				status: data.status,
				failure_reason: data.failure_reason || null,
			};
			if (state.selectedId === caseId) {
				selectedUpdated = true;
			}
		});
		if (!updated) return;
		renderCaseList();
		if (selectedUpdated) {
			if (isProcessingStatus(data.status)) {
				updateStatus(`Extraction ${getStatusLabel(data.status).toLowerCase()}...`);
			} else if (data.status === 'stored') {
				updateStatus('Extraction complete.');
			} else if (data.status === 'failed') {
				updateStatus('Extraction failed.');
			} else if (data.status === 'cancelled') {
				updateStatus('Extraction cancelled.');
			}
			loadCaseDetails(state.selectedId);
		}
	});
}

function initEventHandlers() {
	const datasetFilter = $('#datasetFilter');
	if (datasetFilter) {
		datasetFilter.addEventListener('change', async (event) => {
			state.filterDataset = event.target.value;
			await loadCases();
		});
	}

	const caseSearch = $('#caseSearch');
	if (caseSearch) {
		caseSearch.addEventListener('input', (event) => {
			state.search = event.target.value || '';
			renderCaseList();
		});
	}

	const searchBtn = $('#searchBtn');
	if (searchBtn) {
		searchBtn.addEventListener('click', () => {
			state.search = caseSearch ? caseSearch.value || '' : '';
			renderCaseList();
		});
	}

	const providerSelect = $('#baselineProvider');
	if (providerSelect) {
		state.provider = providerSelect.value || 'openai';
		providerSelect.addEventListener('change', (event) => {
			state.provider = event.target.value || 'openai';
		});
	}

	const pdfStatusFilter = $('#pdfStatusFilter');
	if (pdfStatusFilter) {
		state.pdfStatusFilter = pdfStatusFilter.value || 'all';
		pdfStatusFilter.addEventListener('change', (event) => {
			state.pdfStatusFilter = event.target.value || 'all';
			renderCaseList();
		});
	}

	const runButton = $('#runBaselineBtn');
	if (runButton) {
		runButton.addEventListener('click', () => {
			enqueueBaselineRuns();
		});
	}

	const resolveButton = $('#resolveBaselineBtn');
	if (resolveButton) {
		resolveButton.addEventListener('click', () => {
			resolveBaselineSourcesBulk();
		});
	}
}

async function init() {
	initEventHandlers();
	await loadCases();
	connectSSE();
}

init();
