const assetVersion = window.PEPTIDE_APP_CONFIG?.assetVersion || 'dev';

import(`./js/baseline/controller.js?v=${encodeURIComponent(assetVersion)}`)
	.then(({ initBaseline }) => initBaseline())
	.catch((error) => {
		console.error('Failed to initialize baseline page', error);
	});
