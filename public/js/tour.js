export function initTour({ steps, storageKey, autoStart = true }) {
	let index = 0;
	let overlay = null;
	let tooltip = null;
	let titleEl = null;
	let bodyEl = null;
	let prevBtn = null;
	let nextBtn = null;
	let skipBtn = null;
	let currentEl = null;

	const filteredSteps = steps.filter((step) => document.querySelector(step.selector));
	if (!filteredSteps.length) {
		return { start: () => {} };
	}

	function markSeen() {
		try {
			localStorage.setItem(storageKey, '1');
		} catch {
			// ignore
		}
	}

	function hasSeen() {
		try {
			return localStorage.getItem(storageKey) === '1';
		} catch {
			return false;
		}
	}

	function createUI() {
		overlay = document.createElement('div');
		overlay.className = 'tour-overlay';

		tooltip = document.createElement('div');
		tooltip.className = 'tour-tooltip';

		titleEl = document.createElement('div');
		titleEl.className = 'text-xs font-semibold text-slate-900';
		bodyEl = document.createElement('div');
		bodyEl.className = 'text-xs text-slate-600 mt-2';

		const controls = document.createElement('div');
		controls.className = 'mt-3 flex items-center gap-2';

		prevBtn = document.createElement('button');
		prevBtn.className = 'px-2 py-1 rounded-md border border-slate-200 text-xs hover:bg-slate-100';
		prevBtn.textContent = 'Back';
		prevBtn.addEventListener('click', () => showStep(index - 1));

		nextBtn = document.createElement('button');
		nextBtn.className = 'px-2 py-1 rounded-md bg-indigo-600 text-white text-xs hover:bg-indigo-700';
		nextBtn.textContent = 'Next';
		nextBtn.addEventListener('click', () => showStep(index + 1));

		skipBtn = document.createElement('button');
		skipBtn.className = 'px-2 py-1 rounded-md text-xs text-slate-500 hover:text-slate-700';
		skipBtn.textContent = 'Done';
		skipBtn.addEventListener('click', endTour);

		controls.appendChild(prevBtn);
		controls.appendChild(nextBtn);
		controls.appendChild(skipBtn);

		tooltip.appendChild(titleEl);
		tooltip.appendChild(bodyEl);
		tooltip.appendChild(controls);
		overlay.appendChild(tooltip);

		overlay.addEventListener('click', (event) => {
			if (event.target === overlay) {
				endTour();
			}
		});
	}

	function positionTooltip(element) {
		const rect = element.getBoundingClientRect();
		const scrollX = window.scrollX || window.pageXOffset;
		const scrollY = window.scrollY || window.pageYOffset;
		const padding = 12;

		let top = rect.top + scrollY;
		let left = rect.right + scrollX + padding;

		if (left + tooltip.offsetWidth > scrollX + window.innerWidth) {
			left = rect.left + scrollX;
			top = rect.bottom + scrollY + padding;
		}
		if (top + tooltip.offsetHeight > scrollY + window.innerHeight) {
			top = rect.top + scrollY - tooltip.offsetHeight - padding;
		}

		tooltip.style.top = `${Math.max(top, scrollY + padding)}px`;
		tooltip.style.left = `${Math.max(left, scrollX + padding)}px`;
	}

	function showStep(nextIndex) {
		if (nextIndex < 0 || nextIndex >= filteredSteps.length) {
			endTour();
			return;
		}
		index = nextIndex;
		if (currentEl) currentEl.classList.remove('tour-highlight');
		const step = filteredSteps[index];
		const element = document.querySelector(step.selector);
		if (!element) {
			showStep(index + 1);
			return;
		}
		currentEl = element;
		element.classList.add('tour-highlight');
		element.scrollIntoView({ behavior: 'smooth', block: 'center' });
		titleEl.textContent = step.title;
		bodyEl.textContent = step.body;
		prevBtn.style.visibility = index === 0 ? 'hidden' : 'visible';
		nextBtn.textContent = index === filteredSteps.length - 1 ? 'Finish' : 'Next';

		setTimeout(() => positionTooltip(element), 150);
	}

	function start() {
		if (!overlay) {
			createUI();
		}
		document.body.appendChild(overlay);
		showStep(0);
		window.addEventListener('resize', onResize);
	}

	function endTour() {
		if (currentEl) currentEl.classList.remove('tour-highlight');
		if (overlay && overlay.parentElement) {
			overlay.parentElement.removeChild(overlay);
		}
		window.removeEventListener('resize', onResize);
		markSeen();
	}

	function onResize() {
		if (currentEl) positionTooltip(currentEl);
	}

	if (autoStart && !hasSeen()) {
		setTimeout(() => start(), 400);
	}

	return { start };
}
