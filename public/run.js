import { getRun, getRunHistory } from './js/api.js?v=dev45';

const $ = (sel) => document.querySelector(sel);

function getRunIdFromPath() {
	const parts = window.location.pathname.split('/').filter(Boolean);
	const last = parts[parts.length - 1];
	const runId = parseInt(last, 10);
	return Number.isNaN(runId) ? null : runId;
}

function renderPaper(paper) {
	const container = $('#paperMeta');
	container.innerHTML = '';
	if (!paper) return;

	if (paper.title) {
		container.appendChild(el('div', 'font-medium text-slate-900', paper.title));
	}
	const line = [paper.source?.toUpperCase(), paper.year, paper.doi].filter(Boolean).join(' · ');
	if (line) container.appendChild(el('div', 'text-xs text-slate-500', line));
	if (paper.url) {
		const link = el('a', 'text-xs text-indigo-600 hover:underline', paper.url);
		link.href = paper.url;
		link.target = '_blank';
		container.appendChild(link);
	}
	if (paper.authors?.length) {
		container.appendChild(el('div', 'text-xs text-slate-500', paper.authors.join(', ')));
	}
}

function renderRun(run) {
	const container = $('#runMeta');
	container.innerHTML = '';
	if (!run) return;

	const meta = [
		run.status ? `Status: ${run.status}` : null,
		run.model_provider ? `Provider: ${run.model_provider}` : null,
		run.model_name ? `Model: ${run.model_name}` : null,
		run.created_at ? `Created: ${new Date(run.created_at).toLocaleString()}` : null,
		run.parent_run_id ? `Parent run: ${run.parent_run_id}` : null,
	].filter(Boolean);

	meta.forEach((item) => container.appendChild(el('div', '', item)));

	if (run.pdf_url) {
		const link = el('a', 'text-xs text-indigo-600 hover:underline', run.pdf_url);
		link.href = run.pdf_url;
		link.target = '_blank';
		container.appendChild(link);
	}
}

function setEditLink(runId) {
	const link = $('#editRunLink');
	if (!link || !runId) return;
	link.href = `/runs/${runId}/edit`;
}

function renderEntities(rawJson) {
	const container = $('#entitiesContainer');
	container.innerHTML = '';
	if (!rawJson?.entities?.length) {
		container.appendChild(el('div', 'text-xs text-slate-500', 'No entities found.'));
		return;
	}

	rawJson.entities.forEach((entity, index) => {
		const card = el('div', 'rounded-lg border border-slate-200 bg-slate-50 p-4');
		card.appendChild(el('div', 'text-xs uppercase tracking-wide text-slate-500', `Entity ${index + 1}`));
		card.appendChild(el('div', 'text-sm font-medium text-slate-900 mt-1', entity.type || 'entity'));

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
		if (details) {
			card.appendChild(details);
		}

		if (entity.evidence) {
			const evidenceWrap = el('div', 'mt-3 space-y-2 text-xs text-slate-600');
			Object.entries(entity.evidence).forEach(([field, items]) => {
				const row = el('div', '');
				row.appendChild(el('div', 'font-medium text-slate-700', field));
				(items || []).forEach((item) => {
					const label = [
						item.quote ? `"${item.quote}"` : null,
						item.section ? `section: ${item.section}` : null,
						typeof item.page === 'number' ? `page: ${item.page}` : null,
					].filter(Boolean).join(' · ');
					if (label) row.appendChild(el('div', 'ml-2', label));
				});
				evidenceWrap.appendChild(row);
			});
			card.appendChild(evidenceWrap);
		}

		container.appendChild(card);
	});
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
		row.appendChild(el('div', 'text-[10px] uppercase tracking-wide text-slate-400', label));
		const text = Array.isArray(value) ? value.join(', ') : String(value);
		row.appendChild(el('div', 'text-slate-700 break-words', text));
		wrapper.appendChild(row);
	});
	return wrapper;
}

function renderPrompts(prompts) {
	const container = $('#promptsContainer');
	container.innerHTML = '';
	if (!prompts) {
		container.appendChild(el('div', 'text-xs text-slate-500', 'No prompts recorded.'));
		return;
	}

	const system = prompts.system_prompt || prompts.system || null;
	const user = prompts.user_prompt || prompts.user || null;

	if (system) {
		container.appendChild(renderPromptBlock('System Prompt', system));
	}
	if (user) {
		container.appendChild(renderPromptBlock('User Prompt', user));
	}
}

function renderPromptBlock(label, text) {
	const block = el('div', 'space-y-1');
	block.appendChild(el('div', 'text-xs uppercase tracking-wide text-slate-500', label));
	const pre = el('pre', 'p-3 bg-slate-900 text-slate-100 rounded text-[11px] leading-relaxed max-h-64 overflow-auto');
	pre.textContent = text;
	block.appendChild(pre);
	return block;
}

function renderRawJson(rawJson) {
	const container = $('#rawJson');
	if (!rawJson) {
		container.textContent = '{}';
		return;
	}
	container.textContent = JSON.stringify(rawJson, null, 2);
}

function renderDiff(beforeJson, afterJson) {
	const container = $('#diffContainer');
	container.innerHTML = '';
	if (!beforeJson || !afterJson) {
		container.appendChild(el('div', 'text-xs text-slate-500', 'No diff available.'));
		return;
	}

	const changes = [];
	diffObjects('paper', beforeJson.paper || {}, afterJson.paper || {}, changes);
	diffObjects('entities', beforeJson.entities || [], afterJson.entities || [], changes);
	if ((beforeJson.comment ?? null) !== (afterJson.comment ?? null)) {
		changes.push({ path: 'comment', before: beforeJson.comment ?? null, after: afterJson.comment ?? null });
	}

	if (afterJson.comment) {
		const commentBox = el('div', 'p-3 rounded-md border border-amber-200 bg-amber-50 text-xs text-amber-800');
		commentBox.textContent = afterJson.comment;
		container.appendChild(commentBox);
	}

	if (!changes.length) {
		container.appendChild(el('div', 'text-xs text-slate-500', 'No changes detected.'));
		return;
	}

	changes.forEach((change) => {
		const card = el('div', 'rounded-md border border-slate-200 bg-slate-50 p-3 space-y-3');
		card.appendChild(el('div', 'text-xs font-semibold text-slate-700', humanizePath(change.path)));

		const grid = el('div', 'grid grid-cols-1 md:grid-cols-2 gap-3 text-xs');
		const beforeBox = el('div', 'rounded-md border border-red-200 bg-red-50 p-2 text-red-700');
		beforeBox.appendChild(el('div', 'text-[10px] uppercase tracking-wide text-red-500', 'Before'));
		beforeBox.appendChild(el('div', 'mt-1 break-words', formatValue(change.before)));
		const afterBox = el('div', 'rounded-md border border-emerald-200 bg-emerald-50 p-2 text-emerald-700');
		afterBox.appendChild(el('div', 'text-[10px] uppercase tracking-wide text-emerald-600', 'After'));
		afterBox.appendChild(el('div', 'mt-1 break-words', formatValue(change.after)));
		grid.appendChild(beforeBox);
		grid.appendChild(afterBox);
		card.appendChild(grid);

		const evidence = extractEvidence(afterJson, change.path);
		const reasonBox = el('div', 'text-xs text-slate-600');
		reasonBox.appendChild(el('div', 'text-[10px] uppercase tracking-wide text-slate-500', 'Why'));
		if (evidence.length) {
			evidence.forEach((item) => {
				const label = [
					item.quote ? `"${item.quote}"` : null,
					item.section ? `section: ${item.section}` : null,
					typeof item.page === 'number' ? `page: ${item.page}` : null,
				].filter(Boolean).join(' · ');
				if (label) reasonBox.appendChild(el('div', 'ml-2', label));
			});
		} else if (change.path === 'comment' && afterJson.comment) {
			reasonBox.appendChild(el('div', 'ml-2', afterJson.comment));
		} else {
			reasonBox.appendChild(el('div', 'ml-2', 'No evidence provided.'));
		}
		card.appendChild(reasonBox);

		container.appendChild(card);
	});
}

function resetDiff() {
	const container = $('#diffContainer');
	container.innerHTML = '';
	container.appendChild(el('div', 'text-xs text-slate-500', 'No follow-up diff yet.'));
}

function diffObjects(path, beforeVal, afterVal, changes) {
	if (beforeVal === afterVal) return;
	if (Array.isArray(beforeVal) || Array.isArray(afterVal)) {
		const beforeArr = Array.isArray(beforeVal) ? beforeVal : [];
		const afterArr = Array.isArray(afterVal) ? afterVal : [];
		const max = Math.max(beforeArr.length, afterArr.length);
		for (let i = 0; i < max; i += 1) {
			diffObjects(`${path}[${i}]`, beforeArr[i], afterArr[i], changes);
		}
		return;
	}
	if (isObject(beforeVal) && isObject(afterVal)) {
		const keys = new Set([...Object.keys(beforeVal), ...Object.keys(afterVal)]);
		keys.forEach((key) => {
			if (key === 'evidence') {
				diffEvidence(`${path}.evidence`, beforeVal[key], afterVal[key], changes);
				return;
			}
			diffObjects(`${path}.${key}`, beforeVal[key], afterVal[key], changes);
		});
		return;
	}
	changes.push({ path, before: beforeVal, after: afterVal });
}

function diffEvidence(path, beforeVal, afterVal, changes) {
	const beforeObj = isObject(beforeVal) ? beforeVal : {};
	const afterObj = isObject(afterVal) ? afterVal : {};
	const keys = new Set([...Object.keys(beforeObj), ...Object.keys(afterObj)]);
	keys.forEach((key) => {
		const beforeEntry = beforeObj[key] ?? null;
		const afterEntry = afterObj[key] ?? null;
		if (JSON.stringify(beforeEntry) !== JSON.stringify(afterEntry)) {
			changes.push({ path: `${path}.${key}`, before: beforeEntry, after: afterEntry, kind: 'evidence' });
		}
	});
}

function extractEvidence(afterJson, path) {
	if (path.includes('.evidence.')) return [];
	if (path.startsWith('paper.')) return [];
	const match = path.match(/^entities\[(\d+)\]\.(.+)$/);
	if (!match) return [];
	const index = parseInt(match[1], 10);
	if (Number.isNaN(index)) return [];
	let fieldPath = match[2];
	fieldPath = fieldPath.replace(/\[\d+\]/g, '');
	const entity = afterJson.entities?.[index];
	if (!entity?.evidence) return [];
	const candidates = new Set();
	candidates.add(fieldPath);

	const segments = fieldPath.split('.');
	if (segments.length > 1) {
		candidates.add(segments[segments.length - 1]);
		candidates.add(segments.slice(1).join('.'));
		candidates.add(segments.slice(-2).join('.'));
	}

	['peptide.', 'molecule.', 'conditions.', 'thresholds.'].forEach((prefix) => {
		if (fieldPath.startsWith(prefix)) {
			candidates.add(fieldPath.replace(prefix, ''));
		}
	});

	for (const key of candidates) {
		if (entity.evidence[key]) {
			return entity.evidence[key];
		}
	}
	return [];
}

function isObject(value) {
	return value && typeof value === 'object' && !Array.isArray(value);
}

function formatValue(value) {
	if (value === undefined) return 'undefined';
	if (value === null) return 'null';
	if (typeof value === 'string') return value;
	if (typeof value === 'number' || typeof value === 'boolean') return String(value);
	if (Array.isArray(value)) {
		const preview = value.slice(0, 3).map((item) => formatValue(item));
		return `[${preview.join(', ')}${value.length > 3 ? ', …' : ''}]`;
	}
	if (typeof value === 'object') {
		const keys = Object.keys(value || {}).slice(0, 4);
		if (keys.length === 0) return '{}';
		return `{${keys.join(', ')}${Object.keys(value || {}).length > 4 ? ', …' : ''}}`;
	}
	return String(value);
}

function humanizePath(path) {
	if (path === 'comment') {
		return 'Comment';
	}
	const evidenceMatch = path.match(/^entities\[(\d+)\]\.evidence\.(.+)$/);
	if (evidenceMatch) {
		const index = parseInt(evidenceMatch[1], 10);
		const field = evidenceMatch[2];
		const fieldLabel = field.split('.').map(humanizeLeaf).join(' · ');
		return `Entity ${Number.isNaN(index) ? '?' : index + 1} · Evidence · ${fieldLabel}`;
	}
	if (path.startsWith('paper.')) {
		const key = path.replace('paper.', '');
		return `Paper · ${humanizeLeaf(key)}`;
	}

	const match = path.match(/^entities\[(\d+)\]\.(.+)$/);
	if (!match) return path;
	const index = parseInt(match[1], 10);
	const remainder = match[2];
	const parts = [`Entity ${Number.isNaN(index) ? '?' : index + 1}`];

	const listMatch = remainder.match(/^(labels|morphology|validation_methods|reported_characteristics)\[(\d+)\]$/);
	if (listMatch) {
		parts.push(humanizeLeaf(listMatch[1]));
		parts.push(`#${parseInt(listMatch[2], 10) + 1}`);
		return parts.join(' · ');
	}

	const segments = remainder.split('.');
	const root = segments.shift();
	if (root) {
		parts.push(humanizeLeaf(root));
	}
	if (segments.length > 0) {
		parts.push(humanizeLeaf(segments.join('.')));
	}
	return parts.join(' · ');
}

function humanizeLeaf(key) {
	const map = {
		title: 'Title',
		doi: 'DOI',
		url: 'URL',
		source: 'Source',
		year: 'Year',
		authors: 'Authors',
		type: 'Type',
		peptide: 'Peptide',
		molecule: 'Molecule',
		conditions: 'Conditions',
		thresholds: 'Thresholds',
		labels: 'Labels',
		morphology: 'Morphology',
		validation_methods: 'Validation methods',
		reported_characteristics: 'Reported characteristics',
		process_protocol: 'Process protocol',
		sequence_one_letter: 'Sequence (one-letter)',
		sequence_three_letter: 'Sequence (three-letter)',
		n_terminal_mod: 'N-terminus mod',
		c_terminal_mod: 'C-terminus mod',
		is_hydrogel: 'Hydrogel',
		chemical_formula: 'Chemical formula',
		smiles: 'SMILES',
		inchi: 'InChI',
		ph: 'pH',
		concentration: 'Concentration',
		concentration_units: 'Concentration units',
		temperature_c: 'Temperature (C)',
		cac: 'CAC',
		cgc: 'CGC',
		mgc: 'MGC',
	};
	return map[key] || key.replace(/_/g, ' ');
}

function el(tag, cls, text) {
	const e = document.createElement(tag);
	if (cls) e.className = cls;
	if (text !== undefined) e.textContent = text;
	return e;
}

let currentRunId = null;
let currentRawJson = null;
let followupHasToken = false;

async function loadRun(runId, options = {}) {
	const { resetDiff: shouldResetDiff = true } = options;
	const data = await getRun(runId);
	renderPaper(data.paper);
	renderRun(data.run);
	renderEntities(data.run?.raw_json);
	renderPrompts(data.run?.prompts);
	renderRawJson(data.run?.raw_json);
	if (shouldResetDiff) {
		resetDiff();
	}
	currentRawJson = data.run?.raw_json || null;
	currentRunId = data.run?.id || runId;
	setEditLink(currentRunId);
	await loadHistory(runId);
}

function showSpinner(show) {
	const spinner = $('#followupSpinner');
	if (!spinner) return;
	spinner.classList.toggle('hidden', !show);
}

function setFollowupStatus(message) {
	$('#followupStatus').textContent = message || '';
}

function appendToken(token) {
	const tokenBox = $('#followupTokens');
	tokenBox.classList.remove('hidden');
	if (!followupHasToken) {
		tokenBox.textContent = '';
		followupHasToken = true;
	}
	tokenBox.textContent += token;
	tokenBox.scrollTop = tokenBox.scrollHeight;
}

function resetTokenBox() {
	const tokenBox = $('#followupTokens');
	tokenBox.textContent = '';
	tokenBox.classList.add('hidden');
	followupHasToken = false;
}

function showTokenPlaceholder(message) {
	const tokenBox = $('#followupTokens');
	tokenBox.textContent = message || '';
	tokenBox.classList.remove('hidden');
	followupHasToken = false;
}

async function handleFollowup(runId) {
	const instruction = $('#followupInstruction').value.trim();
	if (!instruction) return;
	const btn = $('#followupBtn');
	btn.disabled = true;
	showTokenPlaceholder('Waiting for model response...');
	showSpinner(true);
	setFollowupStatus('');

	try {
		await streamFollowup(runId, instruction);
		$('#followupInstruction').value = '';
	} catch (err) {
		setFollowupStatus(err.message || 'Follow-up failed');
	} finally {
		showSpinner(false);
		btn.disabled = false;
	}
}

async function streamFollowup(runId, instruction) {
	const response = await fetch(`/api/runs/${runId}/followup-stream`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ instruction }),
	});

	if (!response.ok || !response.body) {
		throw new Error('Failed to start follow-up stream');
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';
	let eventType = 'message';
	let dataLines = [];

	while (true) {
		const { value, done } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });
		let lineBreakIndex;
		while ((lineBreakIndex = buffer.indexOf('\n')) >= 0) {
			let line = buffer.slice(0, lineBreakIndex);
			buffer = buffer.slice(lineBreakIndex + 1);
			if (line.endsWith('\r')) {
				line = line.slice(0, -1);
			}
			if (!line) {
				dispatchSseEvent(eventType, dataLines.join('\n'));
				eventType = 'message';
				dataLines = [];
				continue;
			}
			if (line.startsWith('event:')) {
				eventType = line.replace('event:', '').trim();
				continue;
			}
			if (line.startsWith('data:')) {
				dataLines.push(line.replace('data:', '').trim());
			}
		}
	}
	if (dataLines.length) {
		dispatchSseEvent(eventType, dataLines.join('\n'));
	}
}

function dispatchSseEvent(eventType, dataPayload) {
	let data = {};
	try {
		data = dataPayload ? JSON.parse(dataPayload) : {};
	} catch {
		data = {};
	}

	if (eventType === 'status') {
		const message = data.message || '';
		if (message === 'starting') {
			setFollowupStatus('Preparing follow-up...');
			if (!followupHasToken) {
				showTokenPlaceholder('Waiting for model response...');
			}
		} else if (message === 'streaming') {
			setFollowupStatus('Streaming response...');
			if (!followupHasToken) {
				showTokenPlaceholder('Streaming response...');
			}
		} else if (message === 'non_streaming') {
			setFollowupStatus('Preparing response...');
			if (!followupHasToken) {
				showTokenPlaceholder('Waiting for full response...');
			}
		} else {
			setFollowupStatus(message);
		}
		return;
	}
	if (eventType === 'token') {
		appendToken(data.token || '');
		return;
	}
	if (eventType === 'error') {
		setFollowupStatus(data.message || 'Follow-up failed');
		if (!followupHasToken) {
			showTokenPlaceholder('No streaming tokens received.');
		}
		return;
	}
	if (eventType === 'done') {
		const newPayload = data.payload || null;
		const newRunId = data.run_id;
		if (newPayload && currentRawJson) {
			renderDiff(currentRawJson, newPayload);
		}
		if (newRunId) {
			history.pushState({}, '', `/runs/${newRunId}`);
			loadRun(newRunId, { resetDiff: false });
		} else if (newPayload) {
			renderEntities(newPayload);
			renderRawJson(newPayload);
		}
		if (!followupHasToken) {
			showTokenPlaceholder('No streaming tokens received. Final response applied.');
		}
		setFollowupStatus('Follow-up complete.');
		return;
	}
}

async function init() {
	const runId = getRunIdFromPath();
	if (!runId) {
		$('#paperMeta').textContent = 'Invalid run ID';
		return;
	}
	await loadRun(runId, { resetDiff: true });

	$('#followupBtn').addEventListener('click', () => handleFollowup(runId));
	$('#compareBtn').addEventListener('click', handleCompare);
}

init();

async function loadHistory(runId) {
	const list = $('#historyList');
	if (!list) return;
	list.innerHTML = '';
	const data = await getRunHistory(runId);
	const versions = data.versions || [];

	if (!versions.length) {
		list.appendChild(el('div', '', 'No versions available.'));
		return;
	}

	versions.forEach((version) => {
		const label = `${version.id} · ${version.model_provider || 'unknown'} ${version.model_name || ''}`.trim();
		const row = el('div', 'flex items-center justify-between');
		row.appendChild(el('div', '', label));
		row.appendChild(el('div', 'text-slate-400', version.created_at ? new Date(version.created_at).toLocaleString() : ''));
		list.appendChild(row);
	});

	const selectA = $('#compareA');
	const selectB = $('#compareB');
	[selectA, selectB].forEach((select) => {
		if (!select) return;
		select.innerHTML = '';
		versions.forEach((version) => {
			const option = document.createElement('option');
			option.value = version.id;
			option.textContent = `Run ${version.id}`;
			select.appendChild(option);
		});
	});

	if (versions.length) {
		const sorted = [...versions].sort((a, b) => getRunTimestamp(a) - getRunTimestamp(b));
		const oldest = sorted[0];
		const newest = sorted[sorted.length - 1];
		if (selectA && oldest) selectA.value = oldest.id;
		if (selectB && newest) selectB.value = newest.id;
		setCompareOrderLabel(oldest, newest);
	}
}

async function handleCompare() {
	const selectA = $('#compareA');
	const selectB = $('#compareB');
	if (!selectA || !selectB) return;
	const runA = parseInt(selectA.value, 10);
	const runB = parseInt(selectB.value, 10);
	if (!runA || !runB) return;

	const [dataA, dataB] = await Promise.all([getRun(runA), getRun(runB)]);
	if (dataA.run?.raw_json && dataB.run?.raw_json) {
		const { older, newer } = orderRuns(dataA.run, dataB.run);
		renderDiff(older.raw_json, newer.raw_json);
		setCompareOrderLabel(older, newer);
	} else {
		$('#diffContainer').innerHTML = '';
		$('#diffContainer').appendChild(el('div', 'text-xs text-slate-500', 'Missing run data for comparison.'));
	}
}

function getRunTimestamp(run) {
	if (!run) return 0;
	if (run.created_at) {
		const parsed = Date.parse(run.created_at);
		if (!Number.isNaN(parsed)) return parsed;
	}
	return Number(run.id) || 0;
}

function orderRuns(a, b) {
	const aTime = getRunTimestamp(a);
	const bTime = getRunTimestamp(b);
	if (aTime <= bTime) {
		return { older: a, newer: b };
	}
	return { older: b, newer: a };
}

function setCompareOrderLabel(older, newer) {
	const label = $('#compareOrderLabel');
	if (!label) return;
	if (!older || !newer) {
		label.textContent = '';
		return;
	}
	const olderLabel = `Run ${older.id}${older.created_at ? ` · ${new Date(older.created_at).toLocaleString()}` : ''}`;
	const newerLabel = `Run ${newer.id}${newer.created_at ? ` · ${new Date(newer.created_at).toLocaleString()}` : ''}`;
	label.textContent = `Comparing ${olderLabel} → ${newerLabel}`;
}
