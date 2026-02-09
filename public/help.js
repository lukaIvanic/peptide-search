import { clearExtractionData } from './js/api.js';

const resetBtn = document.querySelector('#resetDbBtn');
const statusEl = document.querySelector('#resetDbStatus');

function setStatus(message, isError = false) {
	if (!statusEl) return;
	statusEl.textContent = message || '';
	statusEl.classList.toggle('text-red-500', Boolean(isError));
}

if (resetBtn) {
	resetBtn.addEventListener('click', async () => {
		const confirmed = window.confirm(
			'This will permanently delete all extracted runs, entities, and papers. Continue?',
		);
		if (!confirmed) return;

		const typed = window.prompt('Type DELETE to confirm.');
		if (typed !== 'DELETE') {
			setStatus('Cancelled. Type DELETE exactly to proceed.', true);
			return;
		}

		resetBtn.disabled = true;
		resetBtn.classList.add('opacity-60', 'cursor-not-allowed');
		setStatus('Deleting extracted runs...');

		try {
			await clearExtractionData();
			setStatus('Extraction database cleared. Refresh pages to see changes.');
		} catch (err) {
			setStatus(err.message || 'Failed to delete extraction data.', true);
		} finally {
			resetBtn.disabled = false;
			resetBtn.classList.remove('opacity-60', 'cursor-not-allowed');
		}
	});
}
