/**
 * Evaluation overview page - displays run cards and handles run creation.
 */
import * as api from './js/api.js';
import { $, el } from './js/renderers.js';

// Model pricing per 1M tokens (approximate)
const MODEL_PRICING = {
	'gpt-4o': { input: 2.50, output: 10.00 },
	'gpt-4o-mini': { input: 0.15, output: 0.60 },
	'gpt-4.1-nano': { input: 0.10, output: 0.40 },
	'mock-model': { input: 0, output: 0 },
};

const STATUS_COLORS = {
	running: 'border-cyan-400',
	completed: 'border-emerald-400',
	partial: 'border-amber-400',
	failed: 'border-rose-400',
};

const STATUS_LABELS = {
	running: 'Running',
	completed: 'Completed',
	partial: 'Partial',
	failed: 'Failed',
};

const SCORED_BATCH_STATUSES = new Set(['completed', 'partial', 'failed']);
const DEFAULT_PROVIDER_METRIC = 'accuracy';
const PROVIDER_METRIC_STORAGE_KEY = 'peptide.evaluation.chart.metric';
const SVG_NS = 'http://www.w3.org/2000/svg';
const COMPACT_FORMAT = new Intl.NumberFormat('en-US', {
	notation: 'compact',
	maximumFractionDigits: 1,
});
const NUMBER_FORMAT = new Intl.NumberFormat('en-US');

const PROVIDER_METRICS = {
	accuracy: {
		id: 'accuracy',
		label: 'Accuracy',
		axisMode: 'percent',
	},
	papers_all_matched: {
		id: 'papers_all_matched',
		label: 'Papers Fully Matched',
		axisMode: 'number',
	},
	total_cost: {
		id: 'total_cost',
		label: 'Total Cost',
		axisMode: 'number',
	},
	total_time: {
		id: 'total_time',
		label: 'Total Time',
		axisMode: 'number',
	},
};

const state = {
	batches: [],
	prompts: [],
	providers: [],
	activePromptId: null,
	sseConnection: null,
	providerChartState: 'loading',
	providerChartError: '',
	providerChartHasAnimated: false,
	providerChartMetric: DEFAULT_PROVIDER_METRIC,
};

let chartResizeTimer = null;

function normalizeProviderKey(provider) {
	return (provider || 'unknown').toString().trim().toLowerCase();
}

function formatProviderName(provider) {
	const key = normalizeProviderKey(provider);
	const descriptor = (state.providers || []).find(
		(item) => normalizeProviderKey(item.provider_id) === key,
	);
	if (descriptor?.label) return descriptor.label;
	if (key === 'openai') return 'OpenAI Full';
	if (key === 'openai-mini') return 'OpenAI Mini';
	if (key === 'openai-nano') return 'OpenAI Nano';
	if (key === 'openrouter') return 'OpenRouter';
	if (key === 'gemini') return 'Gemini';
	if (key === 'deepseek') return 'DeepSeek';
	if (key === 'mock') return 'Mock';
	return provider || 'Unknown';
}

function formatDuration(ms) {
	if (!ms) return '0s';
	const seconds = Math.floor(ms / 1000);
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	const remSeconds = seconds % 60;
	if (minutes < 60) return `${minutes}m ${remSeconds}s`;
	const hours = Math.floor(minutes / 60);
	const remMinutes = minutes % 60;
	return `${hours}h ${remMinutes}m`;
}

function formatTokens(count) {
	if (!count) return '0';
	if (count < 1000) return String(count);
	if (count < 1000000) return `${(count / 1000).toFixed(1)}K`;
	return `${(count / 1000000).toFixed(2)}M`;
}

function formatCost(batch) {
	const pricing = MODEL_PRICING[batch.model_name] || MODEL_PRICING['gpt-4.1-nano'];
	const inputCost = (batch.total_input_tokens / 1_000_000) * pricing.input;
	const outputCost = (batch.total_output_tokens / 1_000_000) * pricing.output;
	const total = inputCost + outputCost;
	if (total < 0.01) return '<$0.01';
	return `$${total.toFixed(2)}`;
}

function formatMatchRate(batch) {
	if (!batch.total_expected_entities) return 'n/a';
	const rate = batch.matched_entities / batch.total_expected_entities;
	return `${(rate * 100).toFixed(0)}%`;
}

function formatDate(isoString) {
	if (!isoString) return '';
	const date = new Date(isoString);
	return date.toLocaleDateString('en-US', {
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
	});
}

function getProgressPercent(batch) {
	if (!batch.total_papers) return 0;
	return ((batch.completed + batch.failed) / batch.total_papers) * 100;
}

function formatCount(value) {
	return NUMBER_FORMAT.format(Number(value || 0));
}

function formatCompactNumber(value) {
	return COMPACT_FORMAT.format(Number(value || 0));
}

function formatPercent(value, digits = 1) {
	if (!Number.isFinite(value)) return 'n/a';
	return `${(value * 100).toFixed(digits)}%`;
}

function formatCurrency(value) {
	if (!Number.isFinite(value)) return 'n/a';
	if (value > 0 && value < 0.01) return '<$0.01';
	if (value >= 100) return `$${value.toFixed(0)}`;
	if (value >= 10) return `$${value.toFixed(1)}`;
	return `$${value.toFixed(2)}`;
}

function formatCurrencyTick(value) {
	if (!Number.isFinite(value)) return 'n/a';
	if (value >= 1000) return `$${formatCompactNumber(value)}`;
	if (value >= 100) return `$${value.toFixed(0)}`;
	if (value >= 10) return `$${value.toFixed(1)}`;
	return `$${value.toFixed(2)}`;
}

function formatDurationTick(ms) {
	if (!Number.isFinite(ms) || ms <= 0) return '0s';
	const seconds = Math.floor(ms / 1000);
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h`;
	const days = Math.floor(hours / 24);
	return `${days}d`;
}

function getMetricConfig(metricId) {
	return PROVIDER_METRICS[metricId] || PROVIDER_METRICS[DEFAULT_PROVIDER_METRIC];
}

function getProviderChartMetricFromStorage() {
	try {
		const stored = window.localStorage.getItem(PROVIDER_METRIC_STORAGE_KEY);
		if (stored && PROVIDER_METRICS[stored]) return stored;
	} catch (_err) {
		// Ignore storage errors; default metric still works.
	}
	return DEFAULT_PROVIDER_METRIC;
}

function persistProviderChartMetric(metricId) {
	try {
		window.localStorage.setItem(PROVIDER_METRIC_STORAGE_KEY, metricId);
	} catch (_err) {
		// Ignore storage errors; state keeps working.
	}
}

function initProviderMetricControls() {
	const select = $('#providerMetricSelect');
	if (!select) return;

	select.innerHTML = '';
	Object.values(PROVIDER_METRICS).forEach((metric) => {
		const option = el('option', '', metric.label);
		option.value = metric.id;
		select.appendChild(option);
	});

	state.providerChartMetric = getProviderChartMetricFromStorage();
	select.value = state.providerChartMetric;

	select.addEventListener('change', (event) => {
		const nextMetric = event.target.value;
		if (!PROVIDER_METRICS[nextMetric]) return;
		state.providerChartMetric = nextMetric;
		persistProviderChartMetric(nextMetric);
		renderProviderAccuracyChart();
	});
}

function getBatchEstimatedCostUsd(batch) {
	const directCost = Number(batch.estimated_cost_usd);
	if (Number.isFinite(directCost) && directCost >= 0) return directCost;
	const pricing = MODEL_PRICING[batch.model_name] || MODEL_PRICING['gpt-4.1-nano'];
	if (!pricing) return 0;
	const inputCost = (Number(batch.total_input_tokens || 0) / 1_000_000) * pricing.input;
	const outputCost = (Number(batch.total_output_tokens || 0) / 1_000_000) * pricing.output;
	return Math.max(0, inputCost + outputCost);
}

function selectFinishedBatches(batches) {
	return batches.filter((batch) => {
		const status = (batch.status || '').toLowerCase();
		const provider = (batch.model_provider || '').toString().trim();
		return SCORED_BATCH_STATUSES.has(status) && provider;
	});
}

function aggregateProviderStats(finishedBatches) {
	const grouped = new Map();
	for (const batch of finishedBatches) {
		const providerRaw = (batch.model_provider || '').toString().trim();
		if (!providerRaw) continue;
		const expected = Number(batch.total_expected_entities || 0);
		const matched = Math.max(0, Number(batch.matched_entities || 0));
		const papersAllMatched = Math.max(0, Number(batch.papers_all_matched || 0));
		const provider = normalizeProviderKey(providerRaw);
		if (!grouped.has(provider)) {
			grouped.set(provider, {
				provider,
				providerLabel: formatProviderName(provider),
				matched: 0,
				expected: 0,
				papersAllMatched: 0,
				papersAllMatchedSamples: 0,
				cost: 0,
				timeMs: 0,
				batches: 0,
			});
		}
		const row = grouped.get(provider);
		row.matched += matched;
		row.expected += Math.max(0, expected);
		if (Number.isFinite(Number(batch.papers_all_matched))) {
			row.papersAllMatched += papersAllMatched;
			row.papersAllMatchedSamples += 1;
		}
		row.cost += getBatchEstimatedCostUsd(batch);
		row.timeMs += Math.max(0, Number(batch.total_time_ms || 0));
		row.batches += 1;
	}

	return Array.from(grouped.values());
}

function computeMetricValue(row, metric) {
	switch (metric.id) {
		case 'accuracy':
			return row.expected > 0 ? row.matched / row.expected : null;
		case 'papers_all_matched':
			return row.papersAllMatchedSamples > 0 ? Number(row.papersAllMatched || 0) : null;
		case 'total_cost':
			return Number(row.cost || 0);
		case 'total_time':
			return Number(row.timeMs || 0);
		default:
			return null;
	}
}

function buildMetricMetaLabel(row, metric, compact) {
	switch (metric.id) {
		case 'accuracy':
			return compact
				? `${formatCount(row.matched)}/${formatCount(row.expected)} · ${row.batches}r`
				: `${formatCount(row.matched)}/${formatCount(row.expected)} matched · ${row.batches} run${row.batches === 1 ? '' : 's'}`;
		case 'papers_all_matched':
			return compact
				? `${formatCount(row.papersAllMatched)} papers · ${row.batches}r`
				: `${formatCount(row.papersAllMatched)} papers fully matched · ${row.batches} run${row.batches === 1 ? '' : 's'}`;
		case 'total_cost':
			return compact
				? `${formatCurrency(row.cost)} total · ${row.batches}r`
				: `${formatCurrency(row.cost)} total spend · ${row.batches} run${row.batches === 1 ? '' : 's'}`;
		case 'total_time':
			return compact
				? `${formatDuration(row.timeMs)} total · ${row.batches}r`
				: `${formatDuration(row.timeMs)} total time · ${row.batches} run${row.batches === 1 ? '' : 's'}`;
		default:
			return '';
	}
}

function formatMetricValue(metric, value) {
	switch (metric.id) {
		case 'accuracy':
			return formatPercent(value, 1);
		case 'papers_all_matched':
			return formatCount(value);
		case 'total_cost':
			return formatCurrency(value);
		case 'total_time':
			return formatDuration(value);
		default:
			return String(value);
	}
}

function formatMetricTick(metric, value) {
	switch (metric.id) {
		case 'accuracy':
			return `${Math.round(value * 100)}%`;
		case 'papers_all_matched':
			return formatCompactNumber(value);
		case 'total_cost':
			return formatCurrencyTick(value);
		case 'total_time':
			return formatDurationTick(value);
		default:
			return String(value);
	}
}

function computeProviderMetricRows(finishedBatches, metric) {
	const aggregated = aggregateProviderStats(finishedBatches);
	const rows = [];

	aggregated.forEach((row) => {
		const metricValue = computeMetricValue(row, metric);
		if (!Number.isFinite(metricValue) || metricValue < 0) {
			return;
		}
		rows.push({
			...row,
			metricValue,
		});
	});

	rows.sort((a, b) => {
		const delta = b.metricValue - a.metricValue;
		if (delta !== 0) return delta;
		if (b.matched !== a.matched) return b.matched - a.matched;
		return b.expected - a.expected;
	});

	const totals = rows.reduce(
		(acc, row) => {
			acc.matched += row.matched;
			acc.expected += row.expected;
			acc.papersAllMatched += row.papersAllMatched;
			acc.cost += row.cost;
			acc.timeMs += row.timeMs;
			acc.runs += row.batches;
			return acc;
		},
		{ matched: 0, expected: 0, papersAllMatched: 0, cost: 0, timeMs: 0, runs: 0 },
	);

	return { rows, totals };
}

function getNiceStep(rawStep) {
	if (!Number.isFinite(rawStep) || rawStep <= 0) return 1;
	const magnitude = 10 ** Math.floor(Math.log10(rawStep));
	const normalized = rawStep / magnitude;
	if (normalized <= 1) return 1 * magnitude;
	if (normalized <= 2) return 2 * magnitude;
	if (normalized <= 5) return 5 * magnitude;
	return 10 * magnitude;
}

function buildAxisTicks(metric, maxValue) {
	if (metric.axisMode === 'percent') {
		const values = [0, 0.25, 0.5, 0.75, 1];
		return {
			max: 1,
			values,
		};
	}

	const safeMax = Math.max(0, maxValue || 0);
	const step = getNiceStep(safeMax / 4 || 1);
	const axisMax = Math.max(step * 4, step);
	return {
		max: axisMax,
		values: [0, step, step * 2, step * 3, step * 4],
	};
}

function truncateLabel(value, maxLength) {
	if (!value || value.length <= maxLength) return value;
	return `${value.slice(0, Math.max(1, maxLength - 1))}\u2026`;
}

function buildProviderChartModel(rows, metric, containerWidth) {
	const width = Math.max(320, Math.floor(containerWidth || 720));
	const compact = width < 720;
	const leftPad = compact ? 122 : 198;
	const rightPad = compact ? 96 : 138;
	const rowHeight = compact ? 46 : 54;
	const barHeight = compact ? 10 : 12;
	const topPad = 24;
	const bottomPad = 44;
	const plotWidth = Math.max(120, width - leftPad - rightPad);
	const axisY = topPad + rows.length * rowHeight + 8;
	const maxMetricValue = rows.reduce((max, row) => Math.max(max, row.metricValue), 0);
	const axis = buildAxisTicks(metric, maxMetricValue);
	const ticks = axis.values.map((value) => ({
		value,
		x: leftPad + plotWidth * (axis.max ? value / axis.max : 0),
		label: formatMetricTick(metric, value),
	}));
	const chartRows = rows.map((row, index) => {
		const ratio = axis.max > 0 ? Math.max(0, Math.min(1, row.metricValue / axis.max)) : 0;
		const yTop = topPad + index * rowHeight;
		const yCenter = yTop + (compact ? 16 : 18);

		return {
			...row,
			providerLabel: compact ? truncateLabel(row.providerLabel, 13) : row.providerLabel,
			ratio,
			valueLabel: formatMetricValue(metric, row.metricValue),
			metaLabel: buildMetricMetaLabel(row, metric, compact),
			yTop,
			yCenter,
			barX: leftPad,
			barY: yCenter - barHeight / 2,
			barWidth: plotWidth * ratio,
			barHeight,
			markerX: leftPad + plotWidth * ratio,
		};
	});

	return {
		width,
		height: axisY + bottomPad,
		compact,
		leftPad,
		plotWidth,
		axisY,
		axisMax: axis.max,
		ticks,
		rows: chartRows,
	};
}

function createSvgNode(tagName, attrs = {}) {
	const node = document.createElementNS(SVG_NS, tagName);
	for (const [key, value] of Object.entries(attrs)) {
		node.setAttribute(key, String(value));
	}
	return node;
}

function renderProviderChartSkeleton(container) {
	const skeleton = el('div', 'provider-accuracy-skeleton', '');
	for (let idx = 0; idx < 3; idx += 1) {
		const row = el('div', 'provider-accuracy-skeleton__row', '');
		row.appendChild(el('div', 'provider-accuracy-skeleton__label', ''));
		row.appendChild(el('div', 'provider-accuracy-skeleton__rail', ''));
		skeleton.appendChild(row);
	}
	container.appendChild(skeleton);
}

function renderProviderAccuracySvg(container, model, metric, options = {}) {
	const { animate = false } = options;
	const animatedFills = [];
	const svg = createSvgNode('svg', {
		class: 'provider-accuracy-svg',
		viewBox: `0 0 ${model.width} ${model.height}`,
		role: 'img',
		'aria-label': `${metric.label} by provider chart`,
	});
	svg.style.width = '100%';
	svg.style.height = 'auto';

	const defs = createSvgNode('defs');
	const gradient = createSvgNode('linearGradient', {
		id: 'providerAccuracyGradient',
		x1: '0%',
		y1: '0%',
		x2: '100%',
		y2: '0%',
	});
	gradient.appendChild(createSvgNode('stop', { offset: '0%', 'stop-color': '#38bdf8' }));
	gradient.appendChild(createSvgNode('stop', { offset: '100%', 'stop-color': '#f472b6' }));
	defs.appendChild(gradient);
	svg.appendChild(defs);

	const guideTop = model.rows.length ? model.rows[0].yTop - 3 : 18;
	for (const tick of model.ticks) {
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-accuracy-grid',
				x1: tick.x,
				y1: guideTop,
				x2: tick.x,
				y2: model.axisY,
			}),
		);
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-accuracy-tick',
				x1: tick.x,
				y1: model.axisY,
				x2: tick.x,
				y2: model.axisY + 6,
			}),
		);
		const tickLabel = createSvgNode('text', {
			class: 'provider-accuracy-tick-label',
			x: tick.x,
			y: model.axisY + 20,
			'text-anchor': 'middle',
		});
		tickLabel.textContent = tick.label;
		svg.appendChild(tickLabel);
	}

	svg.appendChild(
		createSvgNode('line', {
			class: 'provider-accuracy-axis',
			x1: model.leftPad,
			y1: model.axisY,
			x2: model.leftPad + model.plotWidth,
			y2: model.axisY,
		}),
	);

	for (const row of model.rows) {
		const label = createSvgNode('text', {
			class: 'provider-accuracy-label',
			x: 10,
			y: row.yCenter + 4,
		});
		label.textContent = row.providerLabel;
		svg.appendChild(label);

		const meta = createSvgNode('text', {
			class: 'provider-accuracy-meta',
			x: 10,
			y: row.yCenter + 19,
		});
		meta.textContent = row.metaLabel;
		svg.appendChild(meta);

		svg.appendChild(
			createSvgNode('rect', {
				class: 'provider-accuracy-rail',
				x: row.barX,
				y: row.barY,
				width: model.plotWidth,
				height: row.barHeight,
				rx: row.barHeight / 2,
				ry: row.barHeight / 2,
			}),
		);

		const fill = createSvgNode('rect', {
			class: `provider-accuracy-fill${animate ? ' is-animated' : ''}`,
			x: row.barX,
			y: row.barY,
			width: row.barWidth,
			height: row.barHeight,
			rx: row.barHeight / 2,
			ry: row.barHeight / 2,
			fill: 'url(#providerAccuracyGradient)',
		});
		if (animate) {
			fill.style.transform = 'scaleX(0)';
			animatedFills.push(fill);
		}
		svg.appendChild(fill);

		svg.appendChild(
			createSvgNode('circle', {
				class: 'provider-accuracy-marker',
				cx: row.markerX,
				cy: row.yCenter,
				r: model.compact ? 3.5 : 4.5,
			}),
		);

		const value = createSvgNode('text', {
			class: 'provider-accuracy-value',
			x: model.leftPad + model.plotWidth + 8,
			y: row.yCenter + 4,
		});
		value.textContent = row.valueLabel;
		svg.appendChild(value);
	}

	container.appendChild(svg);
	if (animate && animatedFills.length) {
		requestAnimationFrame(() => {
			requestAnimationFrame(() => {
				for (const fill of animatedFills) {
					fill.style.transform = 'scaleX(1)';
				}
			});
		});
	}
}

function buildMetricSummary(metric, rows, totals) {
	if (!rows.length) return 'No provider data';
	switch (metric.id) {
		case 'accuracy':
			return `${rows.length} provider${rows.length === 1 ? '' : 's'} · ${formatCount(totals.matched)}/${formatCount(totals.expected)} matched`;
		case 'papers_all_matched':
			return `${rows.length} provider${rows.length === 1 ? '' : 's'} · ${formatCount(totals.papersAllMatched)} papers fully matched`;
		case 'total_cost':
			return `${rows.length} provider${rows.length === 1 ? '' : 's'} · ${formatCurrency(totals.cost)} total cost`;
		case 'total_time':
			return `${rows.length} provider${rows.length === 1 ? '' : 's'} · ${formatDuration(totals.timeMs)} total time`;
		default:
			return `${rows.length} providers`;
	}
}

function renderProviderAccuracyChart() {
	const container = $('#providerAccuracyChart');
	const plotMount = $('#providerAccuracyPlot');
	const summary = $('#providerAccuracySummary');
	const stateText = $('#providerAccuracyState');
	const metric = getMetricConfig(state.providerChartMetric);
	if (!container || !plotMount) return;
	plotMount.innerHTML = '';

	const isLoading = state.providerChartState === 'loading';
	const isError = state.providerChartState === 'error';
	if (isLoading && !state.batches.length) {
		if (summary) summary.textContent = 'Loading provider analytics...';
		if (stateText) stateText.textContent = 'Loading latest scored evaluation runs...';
		renderProviderChartSkeleton(plotMount);
		return;
	}

	const finishedBatches = selectFinishedBatches(state.batches);
	const { rows, totals } = computeProviderMetricRows(finishedBatches, metric);
	const papersAllMatchedMissing =
		metric.id === 'papers_all_matched' &&
		finishedBatches.length > 0 &&
		finishedBatches.every((batch) => !Number.isFinite(Number(batch.papers_all_matched)));

	if (!rows.length) {
		if (summary) summary.textContent = `No ${metric.label.toLowerCase()} data yet`;
		if (stateText) {
			stateText.textContent = papersAllMatchedMissing
				? 'Papers Fully Matched requires refreshed backend analytics. Restart the server to load this metric.'
				: isError
					? 'Analytics refresh failed. Showing fallback state.'
					: 'Only completed, partial, and failed runs are included.';
		}
		plotMount.appendChild(
			el(
				'div',
				'sw-empty text-xs text-slate-500',
				papersAllMatchedMissing
					? 'Metric unavailable from the current API payload.'
					: state.batches.length
						? 'No providers have enough data for this metric yet.'
						: 'No runs available yet. Start a run to populate analytics.',
			),
		);
		return;
	}

	if (summary) {
		summary.textContent = buildMetricSummary(metric, rows, totals);
	}
	if (stateText) {
		stateText.textContent = isError
			? 'Live refresh hit an error. Displaying last available analytics.'
			: 'Includes completed, partial, and failed runs.';
	}

	const model = buildProviderChartModel(rows, metric, plotMount.clientWidth || container.clientWidth || 720);
	const prefersReducedMotion =
		typeof window !== 'undefined' &&
		typeof window.matchMedia === 'function' &&
		window.matchMedia('(prefers-reduced-motion: reduce)').matches;
	const shouldAnimate = !state.providerChartHasAnimated && !prefersReducedMotion;

	renderProviderAccuracySvg(plotMount, model, metric, { animate: shouldAnimate });
	state.providerChartHasAnimated = true;
}

function queueProviderChartRerender() {
	if (chartResizeTimer) clearTimeout(chartResizeTimer);
	chartResizeTimer = setTimeout(() => {
		chartResizeTimer = null;
		renderProviderAccuracyChart();
	}, 120);
}

function renderBatchCard(batch) {
	const progress = getProgressPercent(batch);
	const statusColor = STATUS_COLORS[batch.status] || 'border-slate-400';
	const statusLabel = STATUS_LABELS[batch.status] || batch.status;

	const card = el('div', `sw-card p-4 hover:shadow-lg transition-shadow border-l-4 ${statusColor}`);
	card.dataset.batchId = batch.batch_id;

	// Header row: name/id + status badge
	const header = el('div', 'flex items-center justify-between mb-3');
	const titleLink = el('a', 'font-semibold text-sm truncate flex-1 mr-2 hover:text-cyan-500 cursor-pointer', batch.label || batch.batch_id);
	titleLink.title = batch.batch_id;
	titleLink.href = `/baseline/${encodeURIComponent(batch.batch_id)}`;

	const statusBadge = el('span', `sw-chip text-[10px] ${batch.status === 'running' ? 'sw-chip--processing' : batch.status === 'completed' ? 'sw-chip--success' : batch.status === 'partial' ? 'sw-chip--warning' : 'sw-chip--error'}`, statusLabel);

	header.appendChild(titleLink);
	header.appendChild(statusBadge);
	card.appendChild(header);

	// Progress bar
	const progressWrapper = el('div', 'mb-3');
	const progressBar = el('div', 'h-2 bg-slate-200 rounded-full overflow-hidden');
	const progressFill = el('div', `h-full transition-all duration-300 ${batch.status === 'running' ? 'bg-cyan-400' : batch.status === 'completed' ? 'bg-emerald-400' : batch.status === 'partial' ? 'bg-amber-400' : 'bg-rose-400'}`);
	progressFill.style.width = `${progress}%`;
	progressBar.appendChild(progressFill);
	progressWrapper.appendChild(progressBar);

	const progressText = el('div', 'flex justify-between text-[10px] text-slate-500 mt-1');
	progressText.appendChild(el('span', '', `${batch.completed}/${batch.total_papers} completed`));
	if (batch.failed > 0) {
		progressText.appendChild(el('span', 'text-rose-500', `${batch.failed} failed`));
	}
	progressWrapper.appendChild(progressText);
	card.appendChild(progressWrapper);

	// Stats grid - 3 columns for more info
	const statsGrid = el('div', 'grid grid-cols-3 gap-2 text-[11px]');

	const addStat = (label, value, highlight = false) => {
		const stat = el('div', 'flex flex-col');
		stat.appendChild(el('span', 'sw-kicker text-[10px] text-slate-400', label));
		stat.appendChild(el('span', highlight ? 'text-emerald-600 font-medium' : 'text-slate-700', value));
		statsGrid.appendChild(stat);
	};

	addStat('Match Rate', formatMatchRate(batch), batch.matched_entities > 0);
	addStat('Cost', formatCost(batch));
	addStat('Time', formatDuration(batch.total_time_ms));
	addStat('Input', `${formatTokens(batch.total_input_tokens)}`);
	addStat('Output', `${formatTokens(batch.total_output_tokens)}`);
	addStat('Model', batch.model_name || batch.model_provider);

	card.appendChild(statsGrid);

	// Action buttons row
	const actionsRow = el('div', 'flex items-center justify-between mt-3 pt-3 border-t border-slate-200');

	const leftActions = el('div', 'flex items-center gap-2');

	// Retry Failed button (only if there are failed runs)
	if (batch.failed > 0 && batch.status !== 'running') {
		const retryBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost text-[10px]');
		retryBtn.innerHTML = `<span class="sw-btn__label">Retry ${batch.failed}</span>`;
		retryBtn.title = `Retry ${batch.failed} failed runs`;
		retryBtn.addEventListener('click', async (e) => {
			e.preventDefault();
			e.stopPropagation();
			await retryBatchFailed(batch.batch_id, retryBtn);
		});
		leftActions.appendChild(retryBtn);
	}

	// Delete button
	const deleteBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost text-[10px] text-rose-500 hover:text-rose-600');
	deleteBtn.innerHTML = '<span class="sw-btn__label">Delete</span>';
	deleteBtn.title = 'Delete this run';
	deleteBtn.addEventListener('click', async (e) => {
		e.preventDefault();
		e.stopPropagation();
		await deleteBatch(batch.batch_id, batch.label || batch.batch_id);
	});
	leftActions.appendChild(deleteBtn);

	actionsRow.appendChild(leftActions);

	// Date on the right
	actionsRow.appendChild(el('span', 'text-[10px] text-slate-500', formatDate(batch.created_at)));

	card.appendChild(actionsRow);

	return card;
}

function renderBatchGrid() {
	const grid = $('#batchGrid');
	const emptyState = $('#emptyState');
	const countEl = $('#batchCount');

	if (!grid) return;

	grid.innerHTML = '';

	if (!state.batches.length) {
		grid.classList.add('hidden');
		emptyState?.classList.remove('hidden');
		if (countEl) countEl.textContent = '0 runs';
		renderProviderAccuracyChart();
		return;
	}

	grid.classList.remove('hidden');
	emptyState?.classList.add('hidden');
	if (countEl) countEl.textContent = `${state.batches.length} run${state.batches.length !== 1 ? 's' : ''}`;

	// Sort by created_at descending (newest first)
	const sorted = [...state.batches].sort((a, b) => {
		const dateA = new Date(a.created_at || 0);
		const dateB = new Date(b.created_at || 0);
		return dateB - dateA;
	});

	for (const batch of sorted) {
		grid.appendChild(renderBatchCard(batch));
	}
	renderProviderAccuracyChart();
}

function updateBatchCard(batchId, updates) {
	const batch = state.batches.find(b => b.batch_id === batchId);
	if (!batch) return;

	Object.assign(batch, updates);

	// Re-render just that card
	const existingCard = document.querySelector(`[data-batch-id="${batchId}"]`);
	if (existingCard) {
		const newCard = renderBatchCard(batch);
		existingCard.replaceWith(newCard);
	}
}

async function loadBatches() {
	try {
		updateStatus('Loading evaluation runs...');
		if (!state.batches.length) {
			state.providerChartState = 'loading';
			state.providerChartError = '';
			renderProviderAccuracyChart();
		}
		const response = await api.get('/api/baseline/batches');
		state.batches = response.batches || [];
		state.providerChartState = 'ready';
		state.providerChartError = '';
		renderBatchGrid();
		updateStatus('');
	} catch (err) {
		console.error('Failed to load batches:', err);
		state.providerChartState = 'error';
		state.providerChartError = err?.message || 'Failed to load provider analytics';
		renderProviderAccuracyChart();
		updateStatus(`Error: ${err.message}`);
	}
}

async function loadPrompts() {
	try {
		const response = await api.getPrompts();
		state.prompts = response.prompts || [];
		state.activePromptId = response.active_prompt_id;
		renderPromptOptions();
	} catch (err) {
		console.error('Failed to load prompts:', err);
	}
}

function renderPromptOptions() {
	const select = $('#batchPrompt');
	if (!select) return;

	select.innerHTML = '';

	const defaultOpt = el('option', '', 'Default (active prompt)');
	defaultOpt.value = '';
	select.appendChild(defaultOpt);

	for (const prompt of state.prompts) {
		const opt = el('option', '', prompt.name + (prompt.is_active ? ' (active)' : ''));
		opt.value = String(prompt.id);
		select.appendChild(opt);
	}
}

function updateStatus(message) {
	const statusEl = $('#statusMessage');
	if (statusEl) statusEl.textContent = message || '';
}

function openNewBatchModal() {
	const modal = $('#newBatchModal');
	if (modal) {
		modal.classList.remove('hidden');
		$('#batchName')?.focus();
	}
}

function closeNewBatchModal() {
	const modal = $('#newBatchModal');
	if (modal) {
		modal.classList.add('hidden');
		// Reset form
		const form = $('#newBatchForm');
		if (form) form.reset();
		syncBatchModelHint();
	}
}

function syncBatchModelHint() {
	const select = $('#batchModel');
	const input = $('#batchCustomModel');
	if (!select || !input) return;
	const descriptor = (state.providers || []).find((item) => item.provider_id === select.value);
	const defaultModel = descriptor?.default_model || '';
	input.placeholder = defaultModel ? `Default: ${defaultModel}` : 'Use provider default';
	if (!input.value) {
		input.value = defaultModel || '';
	}
}

function renderBatchProviderOptions() {
	const select = $('#batchModel');
	if (!select) return;
	const enabled = (state.providers || []).filter((item) => item.enabled);
	if (!enabled.length) return;
	const previous = select.value;
	select.innerHTML = '';
	for (const item of enabled) {
		const option = document.createElement('option');
		option.value = item.provider_id;
		option.textContent = item.label || item.provider_id;
		select.appendChild(option);
	}
	select.value = enabled.some((item) => item.provider_id === previous)
		? previous
		: enabled[0].provider_id;
	syncBatchModelHint();
}

async function loadProviders() {
	try {
		const payload = await api.get('/api/providers');
		state.providers = payload.providers || [];
		renderBatchProviderOptions();
	} catch (err) {
		console.error('Failed to load provider catalog:', err);
	}
}

async function createBatch(name, model, promptId, customModel) {
	const submitBtn = $('#submitBatchBtn');
	const label = submitBtn?.querySelector('.sw-btn__label');

	try {
		if (submitBtn) {
			submitBtn.disabled = true;
			if (label) label.textContent = 'Creating...';
		}

		updateStatus('Creating evaluation run...');

		const response = await api.post('/api/baseline/batch-enqueue', {
			dataset: 'self_assembly',
			label: name || null,
			provider: model,
			model: customModel || null,
			prompt_id: promptId ? parseInt(promptId, 10) : null,
		});

		updateStatus(`Run created: ${response.enqueued} papers queued`);
		closeNewBatchModal();

		// Reload batches to show the new one
		await loadBatches();
	} catch (err) {
		console.error('Failed to create batch:', err);
		updateStatus(`Error: ${err.message}`);
	} finally {
		if (submitBtn) {
			submitBtn.disabled = false;
			if (label) label.textContent = 'Start Run';
		}
	}
}

async function retryBatchFailed(batchId, button) {
	const label = button?.querySelector('.sw-btn__label');
	const originalText = label?.textContent || 'Retry';

	try {
		if (button) {
			button.disabled = true;
			if (label) label.textContent = 'Retrying...';
		}

		updateStatus('Retrying failed runs...');

		const response = await api.post('/api/baseline/batch-retry', {
			batch_id: batchId,
		});

		updateStatus(`Retrying ${response.retried} runs`);

		// Reload batches to show updated status
		await loadBatches();
	} catch (err) {
		console.error('Failed to retry batch:', err);
		updateStatus(`Error: ${err.message}`);
	} finally {
		if (button) {
			button.disabled = false;
			if (label) label.textContent = originalText;
		}
	}
}

async function deleteBatch(batchId, batchLabel) {
	// Confirm deletion
	if (!confirm(`Delete run "${batchLabel}"?\n\nThis will permanently delete the run and all its extraction results.`)) {
		return;
	}

	try {
		updateStatus('Deleting run...');

		await api.del(`/api/baseline/batch/${encodeURIComponent(batchId)}`);

		updateStatus('Run deleted');

		// Remove from state and re-render
		state.batches = state.batches.filter(b => b.batch_id !== batchId);
		state.providerChartState = 'ready';
		state.providerChartError = '';
		renderBatchGrid();
	} catch (err) {
		console.error('Failed to delete batch:', err);
		updateStatus(`Error: ${err.message}`);
	}
}

async function resetBaselineDefaults(button) {
	const confirmed = window.confirm(
		'Reset baseline defaults for all evaluations?\n\nThis removes all local baseline edits and cannot be undone.',
	);
	if (!confirmed) return;

	const label = button?.querySelector('.sw-btn__label');
	const originalLabel = label?.textContent || 'Reset Baseline Data';
	try {
		if (button) {
			button.disabled = true;
		}
		if (label) {
			label.textContent = 'Resetting...';
		}
		updateStatus('Resetting baseline data...');
		const response = await api.resetBaselineDefaults();
		await loadBatches();
		updateStatus(
			`Baseline reset complete (${formatCount(response.total_cases)} cases loaded, ${formatCount(response.deleted_cases)} replaced).`,
		);
	} catch (err) {
		console.error('Failed to reset baseline defaults:', err);
		updateStatus(`Error: ${err.message}`);
	} finally {
		if (button) {
			button.disabled = false;
		}
		if (label) {
			label.textContent = originalLabel;
		}
	}
}

// Debounce state for SSE updates
let sseUpdateTimer = null;
const pendingBatchUpdates = new Set();

function connectSSE() {
	if (state.sseConnection) {
		state.sseConnection.close();
	}

	state.sseConnection = api.createSSEConnection(
		(data) => {
			if (data.event === 'baseline_recompute_finished' || data.event === 'baseline_recompute_progress') {
				queueBatchUpdate(data.data?.batch_id || '__baseline_recompute__');
				return;
			}
			if (data.event === 'run_status' && data.data?.batch_id) {
				// Queue batch update with debouncing
				queueBatchUpdate(data.data.batch_id);
			}
		},
		(err) => {
			console.error('SSE connection error:', err);
			// Reconnect after delay
			setTimeout(() => connectSSE(), 5000);
		}
	);
}

function queueBatchUpdate(batchId) {
	pendingBatchUpdates.add(batchId);

	// Debounce: wait 500ms after last event before fetching
	if (sseUpdateTimer) {
		clearTimeout(sseUpdateTimer);
	}
	sseUpdateTimer = setTimeout(() => {
		processPendingBatchUpdates();
	}, 500);
}

async function processPendingBatchUpdates() {
	if (pendingBatchUpdates.size === 0) return;

	const batchIds = Array.from(pendingBatchUpdates);
	pendingBatchUpdates.clear();
	sseUpdateTimer = null;

	try {
		const response = await api.get('/api/baseline/batches');
		const fetchedBatches = response.batches || [];
		state.providerChartState = 'ready';
		state.providerChartError = '';

		if (batchIds.includes('__baseline_recompute__')) {
			state.batches = fetchedBatches;
			renderBatchGrid();
			return;
		}

		let shouldRenderGrid = false;

		for (const batchId of batchIds) {
			const updatedBatch = fetchedBatches.find(b => b.batch_id === batchId);
			if (updatedBatch) {
				// Update in state
				const idx = state.batches.findIndex(b => b.batch_id === batchId);
				if (idx >= 0) {
					state.batches[idx] = updatedBatch;
				} else {
					// New batch
					state.batches.unshift(updatedBatch);
				}
				// Re-render that card
				const existingCard = document.querySelector(`[data-batch-id="${batchId}"]`);
				if (existingCard) {
					const newCard = renderBatchCard(updatedBatch);
					existingCard.replaceWith(newCard);
				} else {
					// New batch card - re-render grid
					shouldRenderGrid = true;
				}
			}
		}

		if (shouldRenderGrid) {
			renderBatchGrid();
		} else {
			renderProviderAccuracyChart();
		}
	} catch (err) {
		state.providerChartState = 'error';
		state.providerChartError = err?.message || 'Failed to refresh provider analytics';
		renderProviderAccuracyChart();
		console.error('Failed to update batches:', err);
	}
}

function init() {
	// Load data
	initProviderMetricControls();
	renderProviderAccuracyChart();
	loadProviders();
	loadBatches();
	loadPrompts();

	// Connect SSE for live updates
	connectSSE();

	// Event listeners
	$('#newBatchBtn')?.addEventListener('click', openNewBatchModal);
	$('#emptyNewBatchBtn')?.addEventListener('click', openNewBatchModal);
	$('#cancelBatchBtn')?.addEventListener('click', closeNewBatchModal);
	$('#modalBackdrop')?.addEventListener('click', closeNewBatchModal);
	$('#batchModel')?.addEventListener('change', syncBatchModelHint);
	syncBatchModelHint();
	$('#resetBaselineDefaultsBtn')?.addEventListener('click', async () => {
		await resetBaselineDefaults($('#resetBaselineDefaultsBtn'));
	});

	// Form submission
	$('#newBatchForm')?.addEventListener('submit', async (e) => {
		e.preventDefault();
		const name = $('#batchName')?.value?.trim() || '';
		const model = $('#batchModel')?.value || 'openai-nano';
		const customModel = $('#batchCustomModel')?.value?.trim() || null;
		const promptId = $('#batchPrompt')?.value || null;
		await createBatch(name, model, promptId, customModel);
	});

	// Keyboard escape to close modal
	document.addEventListener('keydown', (e) => {
		if (e.key === 'Escape') {
			closeNewBatchModal();
		}
	});

	window.addEventListener('resize', queueProviderChartRerender);
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
	document.addEventListener('DOMContentLoaded', init);
} else {
	init();
}
