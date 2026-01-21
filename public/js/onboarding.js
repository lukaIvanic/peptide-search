export function getMilestones(storageKey) {
	try {
		const raw = localStorage.getItem(storageKey);
		return raw ? JSON.parse(raw) : {};
	} catch {
		return {};
	}
}

export function markMilestone(storageKey, key) {
	const state = getMilestones(storageKey);
	if (state[key]) return state;
	state[key] = true;
	try {
		localStorage.setItem(storageKey, JSON.stringify(state));
	} catch {
		// ignore
	}
	return state;
}

export function resetMilestones(storageKey) {
	try {
		localStorage.removeItem(storageKey);
	} catch {
		// ignore
	}
}

export function renderChecklist({ containerId, progressId, items, storageKey }) {
	const container = document.querySelector(containerId);
	const progress = document.querySelector(progressId);
	if (!container) return;

	const state = getMilestones(storageKey);
	container.innerHTML = '';
	let completed = 0;
	items.forEach((item) => {
		const row = document.createElement('div');
		row.className = 'flex items-center gap-2 text-xs text-slate-600';
		const icon = document.createElement('span');
		const done = Boolean(state[item.key]);
		if (done) completed += 1;
		icon.className = `inline-flex h-4 w-4 items-center justify-center rounded-full ${done ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`;
		icon.textContent = done ? '✓' : '•';
		const label = document.createElement('span');
		label.textContent = item.label;
		row.appendChild(icon);
		row.appendChild(label);
		container.appendChild(row);
	});

	if (progress) {
		progress.textContent = `${completed} of ${items.length} complete`;
	}
}
