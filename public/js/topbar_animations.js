/**
 * Peptide-Themed Top Bar Animations
 * Using Web Animations API + Canvas for rich background effects
 * 30 variations across 10 themes
 */

const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const activeAnimations = new WeakMap();
const activeCanvases = new WeakMap();

// -- Utils --

const roleSelectors = {
	logo: '[data-topbar-role="logo"]',
	title: '[data-topbar-role="title"]',
	subtitle: '[data-topbar-role="subtitle"]',
	badges: '[data-topbar-role="badge"]',
	actions: '[data-topbar-role="actions"]',
};

const resolveOptions = (opts) => {
	if (prefersReducedMotion.matches) {
		return {
			duration: Math.max(opts.duration * 0.5, 1000),
			delay: opts.delay || 0,
			easing: 'ease-out',
			iterations: 1,
			fill: 'forwards',
		};
	}
	return {
		duration: opts.duration || 3000,
		delay: opts.delay || 0,
		easing: opts.easing || 'ease-in-out',
		iterations: opts.iterations ?? 1,
		fill: opts.fill || 'forwards',
		direction: opts.direction || 'normal',
	};
};

const collectElements = (header) => ({
	logo: header.querySelector(roleSelectors.logo),
	title: header.querySelector(roleSelectors.title),
	subtitle: header.querySelector(roleSelectors.subtitle),
	actions: header.querySelector(roleSelectors.actions),
	badges: Array.from(header.querySelectorAll(roleSelectors.badges)),
});

const animate = (el, keyframes, options) => {
	if (!el) return null;
	return el.animate(keyframes, resolveOptions(options));
};

const stopAnimations = (header) => {
	const running = activeAnimations.get(header);
	if (running) {
		running.forEach(anim => anim.cancel && anim.cancel());
		activeAnimations.delete(header);
	}
	const canvasData = activeCanvases.get(header);
	if (canvasData) {
		cancelAnimationFrame(canvasData.rafId);
		activeCanvases.delete(header);
	}
};

// =============================================
// CANVAS BACKGROUND ANIMATIONS
// =============================================

const bgAnimations = {
	
	// 1A. Floating amino acid letters (Original - green)
	aminoAcids: (canvas, ctx, header) => {
		const aminoLetters = ['A', 'R', 'N', 'D', 'C', 'E', 'Q', 'G', 'H', 'I', 'L', 'K', 'M', 'F', 'P', 'S', 'T', 'W', 'Y', 'V'];
		const particles = [];
		for (let i = 0; i < 25; i++) {
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.5,
				vy: (Math.random() - 0.5) * 0.3,
				letter: aminoLetters[Math.floor(Math.random() * aminoLetters.length)],
				size: 10 + Math.random() * 8,
				alpha: 0.1 + Math.random() * 0.2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.x += p.vx; p.y += p.vy;
				if (p.x < -20) p.x = canvas.width + 20;
				if (p.x > canvas.width + 20) p.x = -20;
				if (p.y < -20) p.y = canvas.height + 20;
				if (p.y > canvas.height + 20) p.y = -20;
				ctx.fillStyle = `rgba(16, 185, 129, ${p.alpha})`;
				ctx.font = `bold ${p.size}px "Space Mono", monospace`;
				ctx.fillText(p.letter, p.x, p.y);
			});
		};
	},

	// 1B. Neon amino acids (pink/magenta)
	aminoAcidsNeon: (canvas, ctx, header) => {
		const aminoLetters = ['A', 'R', 'N', 'D', 'C', 'E', 'Q', 'G', 'H', 'I', 'L', 'K', 'M', 'F', 'P', 'S', 'T', 'W', 'Y', 'V'];
		const particles = [];
		for (let i = 0; i < 35; i++) {
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 1.2,
				vy: (Math.random() - 0.5) * 0.8,
				letter: aminoLetters[Math.floor(Math.random() * aminoLetters.length)],
				size: 12 + Math.random() * 10,
				alpha: 0.15 + Math.random() * 0.3,
				pulse: Math.random() * Math.PI * 2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.x += p.vx; p.y += p.vy;
				p.pulse += 0.05;
				if (p.x < -20) p.x = canvas.width + 20;
				if (p.x > canvas.width + 20) p.x = -20;
				if (p.y < -20) p.y = canvas.height + 20;
				if (p.y > canvas.height + 20) p.y = -20;
				const glowAlpha = p.alpha + Math.sin(p.pulse) * 0.1;
				ctx.fillStyle = `rgba(236, 72, 153, ${glowAlpha})`;
				ctx.font = `bold ${p.size}px "Space Mono", monospace`;
				ctx.fillText(p.letter, p.x, p.y);
			});
		};
	},

	// 1C. Ocean amino acids (blue, wave motion)
	aminoAcidsOcean: (canvas, ctx, header) => {
		const aminoLetters = ['A', 'R', 'N', 'D', 'C', 'E', 'Q', 'G', 'H', 'I', 'L', 'K', 'M', 'F', 'P', 'S', 'T', 'W', 'Y', 'V'];
		const particles = [];
		for (let i = 0; i < 20; i++) {
			particles.push({
				x: Math.random() * canvas.width,
				baseY: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.3,
				letter: aminoLetters[Math.floor(Math.random() * aminoLetters.length)],
				size: 10 + Math.random() * 6,
				alpha: 0.1 + Math.random() * 0.15,
				waveOffset: Math.random() * Math.PI * 2,
				waveAmp: 5 + Math.random() * 10,
			});
		}
		let time = 0;
		return () => {
			time += 0.02;
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.x += p.vx;
				const y = p.baseY + Math.sin(time + p.waveOffset) * p.waveAmp;
				if (p.x < -20) p.x = canvas.width + 20;
				if (p.x > canvas.width + 20) p.x = -20;
				ctx.fillStyle = `rgba(14, 165, 233, ${p.alpha})`;
				ctx.font = `bold ${p.size}px "Space Mono", monospace`;
				ctx.fillText(p.letter, p.x, y);
			});
		};
	},

	// 2A. Base pairs (Original)
	basePairs: (canvas, ctx, header) => {
		const bases = [
			{ letter: 'A', color: '#ef4444' },
			{ letter: 'T', color: '#22c55e' },
			{ letter: 'G', color: '#eab308' },
			{ letter: 'C', color: '#3b82f6' },
		];
		const particles = [];
		for (let i = 0; i < 40; i++) {
			const base = bases[Math.floor(Math.random() * bases.length)];
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				vy: 0.3 + Math.random() * 0.7,
				letter: base.letter,
				color: base.color,
				size: 8 + Math.random() * 6,
				alpha: 0.15 + Math.random() * 0.2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.y += p.vy;
				if (p.y > canvas.height + 20) { p.y = -20; p.x = Math.random() * canvas.width; }
				const r = parseInt(p.color.slice(1,3), 16);
				const g = parseInt(p.color.slice(3,5), 16);
				const b = parseInt(p.color.slice(5,7), 16);
				ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${p.alpha})`;
				ctx.font = `bold ${p.size}px "JetBrains Mono", monospace`;
				ctx.fillText(p.letter, p.x, p.y);
			});
		};
	},

	// 2B. Fire base pairs (fast, sparking)
	basePairsFire: (canvas, ctx, header) => {
		const bases = [
			{ letter: 'A', color: '#ef4444' },
			{ letter: 'T', color: '#f97316' },
			{ letter: 'G', color: '#fbbf24' },
			{ letter: 'C', color: '#dc2626' },
		];
		const particles = [];
		for (let i = 0; i < 60; i++) {
			const base = bases[Math.floor(Math.random() * bases.length)];
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				vy: -1 - Math.random() * 2,
				vx: (Math.random() - 0.5) * 0.5,
				letter: base.letter,
				color: base.color,
				size: 8 + Math.random() * 8,
				alpha: 0.2 + Math.random() * 0.3,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.y += p.vy; p.x += p.vx;
				if (p.y < -20) { p.y = canvas.height + 20; p.x = Math.random() * canvas.width; }
				const r = parseInt(p.color.slice(1,3), 16);
				const g = parseInt(p.color.slice(3,5), 16);
				const b = parseInt(p.color.slice(5,7), 16);
				ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${p.alpha})`;
				ctx.font = `bold ${p.size}px "JetBrains Mono", monospace`;
				ctx.fillText(p.letter, p.x, p.y);
			});
		};
	},

	// 2C. Aurora base pairs (purple/green gradient, slow)
	basePairsAurora: (canvas, ctx, header) => {
		const bases = [
			{ letter: 'A', color: '#a855f7' },
			{ letter: 'T', color: '#22c55e' },
			{ letter: 'G', color: '#c084fc' },
			{ letter: 'C', color: '#4ade80' },
		];
		const particles = [];
		for (let i = 0; i < 30; i++) {
			const base = bases[Math.floor(Math.random() * bases.length)];
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				vy: 0.2 + Math.random() * 0.3,
				vx: (Math.random() - 0.5) * 0.2,
				letter: base.letter,
				color: base.color,
				size: 10 + Math.random() * 6,
				alpha: 0.1 + Math.random() * 0.15,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.y += p.vy; p.x += p.vx;
				if (p.y > canvas.height + 20) { p.y = -20; p.x = Math.random() * canvas.width; }
				if (p.x < -20) p.x = canvas.width + 20;
				if (p.x > canvas.width + 20) p.x = -20;
				const r = parseInt(p.color.slice(1,3), 16);
				const g = parseInt(p.color.slice(3,5), 16);
				const b = parseInt(p.color.slice(5,7), 16);
				ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${p.alpha})`;
				ctx.font = `bold ${p.size}px "JetBrains Mono", monospace`;
				ctx.fillText(p.letter, p.x, p.y);
			});
		};
	},

	// 3A. Particles (Original - violet)
	particles: (canvas, ctx, header) => {
		const particles = [];
		const centerX = canvas.width / 2;
		const centerY = canvas.height / 2;
		for (let i = 0; i < 50; i++) {
			particles.push({
				angle: Math.random() * Math.PI * 2,
				radius: 30 + Math.random() * 100,
				speed: 0.005 + Math.random() * 0.01,
				size: 1 + Math.random() * 2,
				alpha: 0.2 + Math.random() * 0.4,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.angle += p.speed;
				const x = centerX + Math.cos(p.angle) * p.radius;
				const y = centerY + Math.sin(p.angle) * p.radius * 0.4;
				ctx.beginPath();
				ctx.arc(x, y, p.size, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(167, 139, 250, ${p.alpha})`;
				ctx.fill();
			});
		};
	},

	// 3B. Solar particles (gold/orange, fast, bursting)
	particlesSolar: (canvas, ctx, header) => {
		const particles = [];
		const centerX = canvas.width / 2;
		const centerY = canvas.height / 2;
		for (let i = 0; i < 70; i++) {
			particles.push({
				angle: Math.random() * Math.PI * 2,
				radius: 20 + Math.random() * 120,
				speed: 0.01 + Math.random() * 0.02,
				size: 1 + Math.random() * 3,
				alpha: 0.3 + Math.random() * 0.4,
				burst: Math.random() * Math.PI * 2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.angle += p.speed;
				p.burst += 0.03;
				const burstOffset = Math.sin(p.burst) * 5;
				const x = centerX + Math.cos(p.angle) * (p.radius + burstOffset);
				const y = centerY + Math.sin(p.angle) * (p.radius + burstOffset) * 0.4;
				ctx.beginPath();
				ctx.arc(x, y, p.size, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(251, 191, 36, ${p.alpha})`;
				ctx.fill();
			});
		};
	},

	// 3C. Ice particles (cyan/white, slow, elegant)
	particlesIce: (canvas, ctx, header) => {
		const particles = [];
		const centerX = canvas.width / 2;
		const centerY = canvas.height / 2;
		for (let i = 0; i < 40; i++) {
			particles.push({
				angle: Math.random() * Math.PI * 2,
				radius: 40 + Math.random() * 80,
				speed: 0.002 + Math.random() * 0.005,
				size: 1 + Math.random() * 2,
				alpha: 0.2 + Math.random() * 0.3,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.angle += p.speed;
				const x = centerX + Math.cos(p.angle) * p.radius;
				const y = centerY + Math.sin(p.angle) * p.radius * 0.5;
				ctx.beginPath();
				ctx.arc(x, y, p.size, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(186, 230, 253, ${p.alpha})`;
				ctx.fill();
			});
		};
	},

	// 4A. Formulas (Original - amber)
	formulas: (canvas, ctx, header) => {
		const formulaList = ['H₂O', 'NaCl', 'C₆H₁₂O₆', 'NH₃', 'CO₂', 'CH₄', 'H₂SO₄', 'NaOH'];
		const particles = [];
		for (let i = 0; i < 15; i++) {
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.3,
				vy: -0.2 - Math.random() * 0.3,
				formula: formulaList[Math.floor(Math.random() * formulaList.length)],
				alpha: 0.1 + Math.random() * 0.15,
				size: 10 + Math.random() * 4,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.x += p.vx; p.y += p.vy;
				if (p.y < -30) { p.y = canvas.height + 30; p.x = Math.random() * canvas.width; }
				ctx.fillStyle = `rgba(251, 191, 36, ${p.alpha})`;
				ctx.font = `${p.size}px "Space Mono", monospace`;
				ctx.fillText(p.formula, p.x, p.y);
			});
		};
	},

	// 4B. Toxic formulas (green, fast, aggressive)
	formulasToxic: (canvas, ctx, header) => {
		const formulaList = ['HCl', 'H₂SO₄', 'HNO₃', 'NaOH', 'NH₃', 'Cl₂', 'F₂', 'BrO₃'];
		const particles = [];
		for (let i = 0; i < 25; i++) {
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.8,
				vy: -0.5 - Math.random() * 0.8,
				formula: formulaList[Math.floor(Math.random() * formulaList.length)],
				alpha: 0.15 + Math.random() * 0.25,
				size: 10 + Math.random() * 6,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.x += p.vx; p.y += p.vy;
				if (p.y < -30) { p.y = canvas.height + 30; p.x = Math.random() * canvas.width; }
				ctx.fillStyle = `rgba(74, 222, 128, ${p.alpha})`;
				ctx.font = `${p.size}px "Space Mono", monospace`;
				ctx.fillText(p.formula, p.x, p.y);
			});
		};
	},

	// 4C. Sunset formulas (orange/coral, gentle)
	formulasSunset: (canvas, ctx, header) => {
		const formulaList = ['C₂H₅OH', 'CH₃COOH', 'C₆H₁₂O₆', 'C₁₂H₂₂O₁₁'];
		const particles = [];
		for (let i = 0; i < 12; i++) {
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.2,
				vy: -0.1 - Math.random() * 0.2,
				formula: formulaList[Math.floor(Math.random() * formulaList.length)],
				alpha: 0.08 + Math.random() * 0.12,
				size: 10 + Math.random() * 4,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			particles.forEach(p => {
				p.x += p.vx; p.y += p.vy;
				if (p.y < -30) { p.y = canvas.height + 30; p.x = Math.random() * canvas.width; }
				ctx.fillStyle = `rgba(251, 146, 60, ${p.alpha})`;
				ctx.font = `${p.size}px "Space Mono", monospace`;
				ctx.fillText(p.formula, p.x, p.y);
			});
		};
	},

	// 5A. Data stream (Original - rose)
	dataStream: (canvas, ctx, header) => {
		const columns = Math.floor(canvas.width / 20);
		const streams = [];
		for (let i = 0; i < columns; i++) {
			streams.push({ x: i * 20, y: Math.random() * canvas.height, speed: 1 + Math.random() * 2, chars: [] });
			for (let j = 0; j < 8; j++) streams[i].chars.push(Math.floor(Math.random() * 10).toString());
		}
		return (time) => {
			ctx.fillStyle = 'rgba(28, 25, 23, 0.1)';
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			ctx.font = '10px "JetBrains Mono", monospace';
			streams.forEach(stream => {
				stream.y += stream.speed;
				if (stream.y > canvas.height + 100) stream.y = -100;
				stream.chars.forEach((char, i) => {
					ctx.fillStyle = `rgba(251, 113, 133, ${Math.max(0.05, 0.3 - i * 0.03)})`;
					ctx.fillText(char, stream.x, stream.y - i * 12);
				});
				if (Math.random() < 0.02) {
					const idx = Math.floor(Math.random() * stream.chars.length);
					stream.chars[idx] = Math.floor(Math.random() * 10).toString();
				}
			});
		};
	},

	// 5B. Electric data stream (blue, glitchy)
	dataStreamElectric: (canvas, ctx, header) => {
		const columns = Math.floor(canvas.width / 18);
		const streams = [];
		for (let i = 0; i < columns; i++) {
			streams.push({ x: i * 18, y: Math.random() * canvas.height, speed: 1.5 + Math.random() * 2.5, chars: [], glitch: 0 });
			for (let j = 0; j < 10; j++) streams[i].chars.push(Math.floor(Math.random() * 10).toString());
		}
		return (time) => {
			ctx.fillStyle = 'rgba(12, 30, 58, 0.15)';
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			ctx.font = '10px "JetBrains Mono", monospace';
			streams.forEach(stream => {
				stream.y += stream.speed;
				if (stream.y > canvas.height + 100) stream.y = -100;
				const glitchOffset = Math.random() < 0.02 ? (Math.random() - 0.5) * 10 : 0;
				stream.chars.forEach((char, i) => {
					ctx.fillStyle = `rgba(96, 165, 250, ${Math.max(0.05, 0.4 - i * 0.035)})`;
					ctx.fillText(char, stream.x + glitchOffset, stream.y - i * 12);
				});
				if (Math.random() < 0.05) {
					const idx = Math.floor(Math.random() * stream.chars.length);
					stream.chars[idx] = Math.floor(Math.random() * 10).toString();
				}
			});
		};
	},

	// 5C. Infrared data stream (red/orange, pulsing)
	dataStreamInfrared: (canvas, ctx, header) => {
		const columns = Math.floor(canvas.width / 22);
		const streams = [];
		for (let i = 0; i < columns; i++) {
			streams.push({ x: i * 22, y: Math.random() * canvas.height, speed: 0.8 + Math.random() * 1.5, chars: [], pulse: Math.random() * Math.PI * 2 });
			for (let j = 0; j < 8; j++) streams[i].chars.push(Math.floor(Math.random() * 10).toString());
		}
		return (time) => {
			ctx.fillStyle = 'rgba(69, 10, 10, 0.1)';
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			ctx.font = '11px "JetBrains Mono", monospace';
			streams.forEach(stream => {
				stream.y += stream.speed;
				stream.pulse += 0.03;
				if (stream.y > canvas.height + 100) stream.y = -100;
				const pulseAlpha = 0.15 + Math.sin(stream.pulse) * 0.1;
				stream.chars.forEach((char, i) => {
					ctx.fillStyle = `rgba(248, 113, 113, ${Math.max(0.05, pulseAlpha + 0.2 - i * 0.03)})`;
					ctx.fillText(char, stream.x, stream.y - i * 12);
				});
			});
		};
	},

	// 6A. H-Bonds (Original - blue)
	hBonds: (canvas, ctx, header) => {
		const bonds = [];
		for (let i = 0; i < 20; i++) {
			bonds.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.4, vy: (Math.random() - 0.5) * 0.4,
				length: 15 + Math.random() * 20, angle: Math.random() * Math.PI * 2,
				rotSpeed: (Math.random() - 0.5) * 0.02, alpha: 0.15 + Math.random() * 0.2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			bonds.forEach(b => {
				b.x += b.vx; b.y += b.vy; b.angle += b.rotSpeed;
				if (b.x < -30) b.x = canvas.width + 30;
				if (b.x > canvas.width + 30) b.x = -30;
				if (b.y < -30) b.y = canvas.height + 30;
				if (b.y > canvas.height + 30) b.y = -30;
				const x2 = b.x + Math.cos(b.angle) * b.length;
				const y2 = b.y + Math.sin(b.angle) * b.length;
				ctx.setLineDash([3, 3]);
				ctx.strokeStyle = `rgba(147, 197, 253, ${b.alpha})`;
				ctx.beginPath(); ctx.moveTo(b.x, b.y); ctx.lineTo(x2, y2); ctx.stroke();
				ctx.setLineDash([]);
				ctx.beginPath(); ctx.arc(b.x, b.y, 3, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(59, 130, 246, ${b.alpha + 0.1})`; ctx.fill();
				ctx.beginPath(); ctx.arc(x2, y2, 3, 0, Math.PI * 2); ctx.fill();
			});
		};
	},

	// 6B. Mint H-Bonds (teal, crisp)
	hBondsMint: (canvas, ctx, header) => {
		const bonds = [];
		for (let i = 0; i < 25; i++) {
			bonds.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.5, vy: (Math.random() - 0.5) * 0.5,
				length: 12 + Math.random() * 18, angle: Math.random() * Math.PI * 2,
				rotSpeed: (Math.random() - 0.5) * 0.03, alpha: 0.2 + Math.random() * 0.2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			bonds.forEach(b => {
				b.x += b.vx; b.y += b.vy; b.angle += b.rotSpeed;
				if (b.x < -30) b.x = canvas.width + 30;
				if (b.x > canvas.width + 30) b.x = -30;
				if (b.y < -30) b.y = canvas.height + 30;
				if (b.y > canvas.height + 30) b.y = -30;
				const x2 = b.x + Math.cos(b.angle) * b.length;
				const y2 = b.y + Math.sin(b.angle) * b.length;
				ctx.setLineDash([2, 4]);
				ctx.strokeStyle = `rgba(153, 246, 228, ${b.alpha})`;
				ctx.beginPath(); ctx.moveTo(b.x, b.y); ctx.lineTo(x2, y2); ctx.stroke();
				ctx.setLineDash([]);
				ctx.beginPath(); ctx.arc(b.x, b.y, 2.5, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(45, 212, 191, ${b.alpha + 0.1})`; ctx.fill();
				ctx.beginPath(); ctx.arc(x2, y2, 2.5, 0, Math.PI * 2); ctx.fill();
			});
		};
	},

	// 6C. Twilight H-Bonds (fuchsia, glowing)
	hBondsTwilight: (canvas, ctx, header) => {
		const bonds = [];
		for (let i = 0; i < 18; i++) {
			bonds.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
				length: 18 + Math.random() * 25, angle: Math.random() * Math.PI * 2,
				rotSpeed: (Math.random() - 0.5) * 0.015, alpha: 0.15 + Math.random() * 0.2,
				pulse: Math.random() * Math.PI * 2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			bonds.forEach(b => {
				b.x += b.vx; b.y += b.vy; b.angle += b.rotSpeed; b.pulse += 0.03;
				if (b.x < -30) b.x = canvas.width + 30;
				if (b.x > canvas.width + 30) b.x = -30;
				if (b.y < -30) b.y = canvas.height + 30;
				if (b.y > canvas.height + 30) b.y = -30;
				const x2 = b.x + Math.cos(b.angle) * b.length;
				const y2 = b.y + Math.sin(b.angle) * b.length;
				const glowAlpha = b.alpha + Math.sin(b.pulse) * 0.1;
				ctx.setLineDash([4, 2]);
				ctx.strokeStyle = `rgba(245, 208, 254, ${glowAlpha})`;
				ctx.beginPath(); ctx.moveTo(b.x, b.y); ctx.lineTo(x2, y2); ctx.stroke();
				ctx.setLineDash([]);
				ctx.beginPath(); ctx.arc(b.x, b.y, 3.5, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(217, 70, 239, ${glowAlpha + 0.15})`; ctx.fill();
				ctx.beginPath(); ctx.arc(x2, y2, 3.5, 0, Math.PI * 2); ctx.fill();
			});
		};
	},

	// 7A. Lipids (Original - teal)
	lipids: (canvas, ctx, header) => {
		const lipids = [];
		for (let i = 0; i < 30; i++) {
			lipids.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.6, vy: (Math.random() - 0.5) * 0.3,
				angle: Math.random() * Math.PI * 2, rotSpeed: (Math.random() - 0.5) * 0.01,
				alpha: 0.2 + Math.random() * 0.2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			lipids.forEach(l => {
				l.x += l.vx; l.y += l.vy; l.angle += l.rotSpeed;
				if (l.x < -20) l.x = canvas.width + 20;
				if (l.x > canvas.width + 20) l.x = -20;
				if (l.y < -20) l.y = canvas.height + 20;
				if (l.y > canvas.height + 20) l.y = -20;
				ctx.save(); ctx.translate(l.x, l.y); ctx.rotate(l.angle);
				ctx.beginPath(); ctx.arc(0, 0, 4, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(45, 212, 191, ${l.alpha + 0.2})`; ctx.fill();
				ctx.strokeStyle = `rgba(94, 234, 212, ${l.alpha})`; ctx.lineWidth = 1.5;
				ctx.beginPath(); ctx.moveTo(-2, 4); ctx.lineTo(-2, 14);
				ctx.moveTo(2, 4); ctx.lineTo(2, 14); ctx.stroke();
				ctx.restore();
			});
		};
	},

	// 7B. Golden lipids
	lipidsGold: (canvas, ctx, header) => {
		const lipids = [];
		for (let i = 0; i < 35; i++) {
			lipids.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.7, vy: (Math.random() - 0.5) * 0.4,
				angle: Math.random() * Math.PI * 2, rotSpeed: (Math.random() - 0.5) * 0.015,
				alpha: 0.25 + Math.random() * 0.25,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			lipids.forEach(l => {
				l.x += l.vx; l.y += l.vy; l.angle += l.rotSpeed;
				if (l.x < -20) l.x = canvas.width + 20;
				if (l.x > canvas.width + 20) l.x = -20;
				if (l.y < -20) l.y = canvas.height + 20;
				if (l.y > canvas.height + 20) l.y = -20;
				ctx.save(); ctx.translate(l.x, l.y); ctx.rotate(l.angle);
				ctx.beginPath(); ctx.arc(0, 0, 4, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(251, 191, 36, ${l.alpha + 0.2})`; ctx.fill();
				ctx.strokeStyle = `rgba(252, 211, 77, ${l.alpha})`; ctx.lineWidth = 1.5;
				ctx.beginPath(); ctx.moveTo(-2, 4); ctx.lineTo(-2, 14);
				ctx.moveTo(2, 4); ctx.lineTo(2, 14); ctx.stroke();
				ctx.restore();
			});
		};
	},

	// 7C. Deep sea lipids (bioluminescent)
	lipidsDeep: (canvas, ctx, header) => {
		const lipids = [];
		for (let i = 0; i < 25; i++) {
			lipids.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.4, vy: (Math.random() - 0.5) * 0.2,
				angle: Math.random() * Math.PI * 2, rotSpeed: (Math.random() - 0.5) * 0.008,
				alpha: 0.15 + Math.random() * 0.2, pulse: Math.random() * Math.PI * 2,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			lipids.forEach(l => {
				l.x += l.vx; l.y += l.vy; l.angle += l.rotSpeed; l.pulse += 0.02;
				if (l.x < -20) l.x = canvas.width + 20;
				if (l.x > canvas.width + 20) l.x = -20;
				if (l.y < -20) l.y = canvas.height + 20;
				if (l.y > canvas.height + 20) l.y = -20;
				const glowAlpha = l.alpha + Math.sin(l.pulse) * 0.1;
				ctx.save(); ctx.translate(l.x, l.y); ctx.rotate(l.angle);
				ctx.beginPath(); ctx.arc(0, 0, 4, 0, Math.PI * 2);
				ctx.fillStyle = `rgba(59, 130, 246, ${glowAlpha + 0.2})`; ctx.fill();
				ctx.strokeStyle = `rgba(96, 165, 250, ${glowAlpha})`; ctx.lineWidth = 1.5;
				ctx.beginPath(); ctx.moveTo(-2, 4); ctx.lineTo(-2, 14);
				ctx.moveTo(2, 4); ctx.lineTo(2, 14); ctx.stroke();
				ctx.restore();
			});
		};
	},

	// 8A. Lattice (Original - indigo)
	lattice: (canvas, ctx, header) => {
		const gridSize = 25;
		const offset = { x: 0, y: 0 };
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			offset.x += 0.3; offset.y += 0.2;
			if (offset.x > gridSize) offset.x = 0;
			if (offset.y > gridSize) offset.y = 0;
			ctx.strokeStyle = 'rgba(99, 102, 241, 0.15)'; ctx.lineWidth = 1;
			for (let x = -gridSize + offset.x; x < canvas.width + gridSize; x += gridSize) {
				ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
			}
			for (let y = -gridSize + offset.y; y < canvas.height + gridSize; y += gridSize) {
				ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
			}
			ctx.fillStyle = 'rgba(129, 140, 248, 0.3)';
			for (let x = -gridSize + offset.x; x < canvas.width + gridSize; x += gridSize) {
				for (let y = -gridSize + offset.y; y < canvas.height + gridSize; y += gridSize) {
					ctx.beginPath(); ctx.arc(x, y, 2, 0, Math.PI * 2); ctx.fill();
				}
			}
		};
	},

	// 8B. Ruby lattice
	latticeRuby: (canvas, ctx, header) => {
		const gridSize = 22;
		const offset = { x: 0, y: 0 };
		let pulse = 0;
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			offset.x += 0.4; offset.y += 0.3; pulse += 0.02;
			if (offset.x > gridSize) offset.x = 0;
			if (offset.y > gridSize) offset.y = 0;
			ctx.strokeStyle = 'rgba(225, 29, 72, 0.2)'; ctx.lineWidth = 1;
			for (let x = -gridSize + offset.x; x < canvas.width + gridSize; x += gridSize) {
				ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
			}
			for (let y = -gridSize + offset.y; y < canvas.height + gridSize; y += gridSize) {
				ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
			}
			const sparkle = 0.25 + Math.sin(pulse) * 0.15;
			ctx.fillStyle = `rgba(244, 63, 94, ${sparkle})`;
			for (let x = -gridSize + offset.x; x < canvas.width + gridSize; x += gridSize) {
				for (let y = -gridSize + offset.y; y < canvas.height + gridSize; y += gridSize) {
					ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2); ctx.fill();
				}
			}
		};
	},

	// 8C. Diamond lattice (white/silver)
	latticeDiamond: (canvas, ctx, header) => {
		const gridSize = 28;
		const offset = { x: 0, y: 0 };
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			offset.x += 0.2; offset.y += 0.15;
			if (offset.x > gridSize) offset.x = 0;
			if (offset.y > gridSize) offset.y = 0;
			ctx.strokeStyle = 'rgba(203, 213, 225, 0.2)'; ctx.lineWidth = 1;
			for (let x = -gridSize + offset.x; x < canvas.width + gridSize; x += gridSize) {
				ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
			}
			for (let y = -gridSize + offset.y; y < canvas.height + gridSize; y += gridSize) {
				ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
			}
			ctx.fillStyle = 'rgba(241, 245, 249, 0.4)';
			for (let x = -gridSize + offset.x; x < canvas.width + gridSize; x += gridSize) {
				for (let y = -gridSize + offset.y; y < canvas.height + gridSize; y += gridSize) {
					ctx.beginPath(); ctx.arc(x, y, 1.5, 0, Math.PI * 2); ctx.fill();
				}
			}
		};
	},

	// 9A. UV Sweep (Original - lime)
	uvSweep: (canvas, ctx, header) => {
		let sweepX = -100;
		const spots = [];
		for (let i = 0; i < 20; i++) {
			spots.push({ x: Math.random() * canvas.width, y: Math.random() * canvas.height, size: 3 + Math.random() * 5, glowIntensity: 0 });
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			sweepX += 2;
			if (sweepX > canvas.width + 100) sweepX = -100;
			const gradient = ctx.createLinearGradient(sweepX - 50, 0, sweepX + 50, 0);
			gradient.addColorStop(0, 'rgba(132, 204, 22, 0)');
			gradient.addColorStop(0.5, 'rgba(132, 204, 22, 0.3)');
			gradient.addColorStop(1, 'rgba(132, 204, 22, 0)');
			ctx.fillStyle = gradient;
			ctx.fillRect(sweepX - 50, 0, 100, canvas.height);
			spots.forEach(spot => {
				if (Math.abs(spot.x - sweepX) < 30) spot.glowIntensity = Math.min(1, spot.glowIntensity + 0.1);
				else spot.glowIntensity = Math.max(0, spot.glowIntensity - 0.02);
				if (spot.glowIntensity > 0) {
					ctx.beginPath(); ctx.arc(spot.x, spot.y, spot.size + 4, 0, Math.PI * 2);
					ctx.fillStyle = `rgba(163, 230, 53, ${spot.glowIntensity * 0.4})`; ctx.fill();
				}
				ctx.beginPath(); ctx.arc(spot.x, spot.y, spot.size, 0, Math.PI * 2);
				ctx.fillStyle = spot.glowIntensity > 0 ? `rgba(132, 204, 22, ${0.5 + spot.glowIntensity * 0.5})` : 'rgba(54, 83, 20, 0.4)';
				ctx.fill();
			});
		};
	},

	// 9B. Party UV sweep (purple/pink)
	uvSweepParty: (canvas, ctx, header) => {
		let sweepX = -100;
		const spots = [];
		for (let i = 0; i < 25; i++) {
			spots.push({ x: Math.random() * canvas.width, y: Math.random() * canvas.height, size: 4 + Math.random() * 6, glowIntensity: 0 });
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			sweepX += 3;
			if (sweepX > canvas.width + 100) sweepX = -100;
			const gradient = ctx.createLinearGradient(sweepX - 60, 0, sweepX + 60, 0);
			gradient.addColorStop(0, 'rgba(232, 121, 249, 0)');
			gradient.addColorStop(0.5, 'rgba(232, 121, 249, 0.4)');
			gradient.addColorStop(1, 'rgba(232, 121, 249, 0)');
			ctx.fillStyle = gradient;
			ctx.fillRect(sweepX - 60, 0, 120, canvas.height);
			spots.forEach(spot => {
				if (Math.abs(spot.x - sweepX) < 40) spot.glowIntensity = Math.min(1, spot.glowIntensity + 0.15);
				else spot.glowIntensity = Math.max(0, spot.glowIntensity - 0.03);
				if (spot.glowIntensity > 0) {
					ctx.beginPath(); ctx.arc(spot.x, spot.y, spot.size + 6, 0, Math.PI * 2);
					ctx.fillStyle = `rgba(244, 114, 182, ${spot.glowIntensity * 0.5})`; ctx.fill();
				}
				ctx.beginPath(); ctx.arc(spot.x, spot.y, spot.size, 0, Math.PI * 2);
				ctx.fillStyle = spot.glowIntensity > 0 ? `rgba(232, 121, 249, ${0.5 + spot.glowIntensity * 0.5})` : 'rgba(88, 28, 135, 0.5)';
				ctx.fill();
			});
		};
	},

	// 9C. Bio UV sweep (cyan, soft)
	uvSweepBio: (canvas, ctx, header) => {
		let sweepX = -100;
		const spots = [];
		for (let i = 0; i < 18; i++) {
			spots.push({ x: Math.random() * canvas.width, y: Math.random() * canvas.height, size: 3 + Math.random() * 5, glowIntensity: 0, pulse: Math.random() * Math.PI * 2 });
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			sweepX += 1.5;
			if (sweepX > canvas.width + 100) sweepX = -100;
			const gradient = ctx.createLinearGradient(sweepX - 50, 0, sweepX + 50, 0);
			gradient.addColorStop(0, 'rgba(34, 211, 238, 0)');
			gradient.addColorStop(0.5, 'rgba(34, 211, 238, 0.25)');
			gradient.addColorStop(1, 'rgba(34, 211, 238, 0)');
			ctx.fillStyle = gradient;
			ctx.fillRect(sweepX - 50, 0, 100, canvas.height);
			spots.forEach(spot => {
				spot.pulse += 0.02;
				if (Math.abs(spot.x - sweepX) < 30) spot.glowIntensity = Math.min(1, spot.glowIntensity + 0.08);
				else spot.glowIntensity = Math.max(0, spot.glowIntensity - 0.015);
				const baseGlow = spot.glowIntensity + Math.sin(spot.pulse) * 0.1;
				if (baseGlow > 0) {
					ctx.beginPath(); ctx.arc(spot.x, spot.y, spot.size + 4, 0, Math.PI * 2);
					ctx.fillStyle = `rgba(103, 232, 249, ${baseGlow * 0.35})`; ctx.fill();
				}
				ctx.beginPath(); ctx.arc(spot.x, spot.y, spot.size, 0, Math.PI * 2);
				ctx.fillStyle = baseGlow > 0.1 ? `rgba(34, 211, 238, ${0.4 + baseGlow * 0.5})` : 'rgba(22, 78, 99, 0.4)';
				ctx.fill();
			});
		};
	},

	// 10A. Documents (Original - fuchsia)
	documents: (canvas, ctx, header) => {
		const pages = [];
		for (let i = 0; i < 12; i++) {
			pages.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: -0.5 - Math.random() * 0.5, vy: (Math.random() - 0.5) * 0.3,
				width: 20 + Math.random() * 15, height: 25 + Math.random() * 15,
				alpha: 0.1 + Math.random() * 0.15, rotation: (Math.random() - 0.5) * 0.3,
				rotSpeed: (Math.random() - 0.5) * 0.005,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			pages.forEach(p => {
				p.x += p.vx; p.y += p.vy; p.rotation += p.rotSpeed;
				if (p.x < -50) { p.x = canvas.width + 50; p.y = Math.random() * canvas.height; }
				ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rotation);
				ctx.fillStyle = `rgba(217, 70, 239, ${p.alpha})`;
				ctx.fillRect(-p.width/2, -p.height/2, p.width, p.height);
				ctx.fillStyle = `rgba(240, 171, 252, ${p.alpha + 0.1})`;
				for (let i = 0; i < 4; i++) {
					ctx.fillRect(-p.width/2 + 3, -p.height/2 + 4 + i * 5, p.width * (0.5 + Math.random() * 0.4), 2);
				}
				ctx.restore();
			});
		};
	},

	// 10B. Matrix documents (green, falling)
	documentsMatrix: (canvas, ctx, header) => {
		const pages = [];
		for (let i = 0; i < 18; i++) {
			pages.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: (Math.random() - 0.5) * 0.3, vy: 1 + Math.random() * 1.5,
				width: 18 + Math.random() * 12, height: 22 + Math.random() * 12,
				alpha: 0.15 + Math.random() * 0.2, rotation: (Math.random() - 0.5) * 0.2,
				rotSpeed: (Math.random() - 0.5) * 0.003,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			pages.forEach(p => {
				p.x += p.vx; p.y += p.vy; p.rotation += p.rotSpeed;
				if (p.y > canvas.height + 50) { p.y = -50; p.x = Math.random() * canvas.width; }
				ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rotation);
				ctx.fillStyle = `rgba(34, 197, 94, ${p.alpha})`;
				ctx.fillRect(-p.width/2, -p.height/2, p.width, p.height);
				ctx.fillStyle = `rgba(134, 239, 172, ${p.alpha + 0.1})`;
				for (let i = 0; i < 4; i++) {
					ctx.fillRect(-p.width/2 + 3, -p.height/2 + 4 + i * 5, p.width * (0.5 + Math.random() * 0.4), 2);
				}
				ctx.restore();
			});
		};
	},

	// 10C. Blueprint documents (blue, precise)
	documentsBlueprint: (canvas, ctx, header) => {
		const pages = [];
		for (let i = 0; i < 10; i++) {
			pages.push({
				x: Math.random() * canvas.width, y: Math.random() * canvas.height,
				vx: -0.3 - Math.random() * 0.3, vy: (Math.random() - 0.5) * 0.2,
				width: 22 + Math.random() * 12, height: 28 + Math.random() * 12,
				alpha: 0.1 + Math.random() * 0.12, rotation: (Math.random() - 0.5) * 0.15,
				rotSpeed: (Math.random() - 0.5) * 0.002,
			});
		}
		return (time) => {
			ctx.clearRect(0, 0, canvas.width, canvas.height);
			pages.forEach(p => {
				p.x += p.vx; p.y += p.vy; p.rotation += p.rotSpeed;
				if (p.x < -50) { p.x = canvas.width + 50; p.y = Math.random() * canvas.height; }
				ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rotation);
				ctx.fillStyle = `rgba(59, 130, 246, ${p.alpha})`;
				ctx.fillRect(-p.width/2, -p.height/2, p.width, p.height);
				ctx.fillStyle = `rgba(191, 219, 254, ${p.alpha + 0.1})`;
				for (let i = 0; i < 4; i++) {
					ctx.fillRect(-p.width/2 + 3, -p.height/2 + 4 + i * 6, p.width * (0.6 + Math.random() * 0.3), 2);
				}
				ctx.restore();
			});
		};
	},
};

// Start canvas animation
const startCanvasAnimation = (canvas, bgType, header) => {
	if (!canvas || !bgType || !bgAnimations[bgType]) return;
	const rect = canvas.parentElement.getBoundingClientRect();
	canvas.width = rect.width;
	canvas.height = rect.height;
	const ctx = canvas.getContext('2d');
	const animFn = bgAnimations[bgType](canvas, ctx, header);
	let rafId;
	const loop = (time) => { animFn(time); rafId = requestAnimationFrame(loop); };
	rafId = requestAnimationFrame(loop);
	activeCanvases.set(header, { rafId, canvas, ctx });
};

// =============================================
// WAAPI ANIMATION VARIANTS
// =============================================

const variants = {

	// ===== 1. PEPTIDE BOND SERIES =====
	
	// 01A - Original
	peptideBond: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		const canvas = header.querySelector('.topbar-bg-canvas');
		startCanvasAnimation(canvas, 'aminoAcids', header);
		const aminos = logo?.querySelectorAll('.amino') || [];
		const bonds = logo?.querySelectorAll('.bond') || [];
		const labels = logo?.querySelectorAll('.bond-label') || [];
		aminos.forEach((amino, i) => {
			animations.push(animate(amino, [
				{ opacity: 0, transform: 'scale(0)' },
				{ opacity: 1, transform: 'scale(1.2)', offset: 0.6 },
				{ opacity: 1, transform: 'scale(1)' }
			], { duration: 800, delay: i * 400, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' }));
		});
		bonds.forEach((bond, i) => {
			animations.push(animate(bond, [{ strokeDashoffset: '8' }, { strokeDashoffset: '0' }], { duration: 600, delay: 1200 + i * 400, easing: 'ease-out' }));
		});
		labels.forEach((label, i) => {
			animations.push(animate(label, [{ opacity: 0, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 400, delay: 1800 + i * 300 }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 800, delay: 500 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1000 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: 2200 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 01B - Neon Synthesis (faster, intense)
	peptideBondNeon: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'aminoAcidsNeon', header);
		const aminos = logo?.querySelectorAll('.amino') || [];
		const bonds = logo?.querySelectorAll('.bond') || [];
		const labels = logo?.querySelectorAll('.bond-label') || [];
		aminos.forEach((amino, i) => {
			animations.push(animate(amino, [
				{ opacity: 0, transform: 'scale(0) rotate(-180deg)' },
				{ opacity: 1, transform: 'scale(1.4) rotate(0deg)', offset: 0.5 },
				{ opacity: 1, transform: 'scale(1) rotate(0deg)' }
			], { duration: 500, delay: i * 200, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' }));
		});
		bonds.forEach((bond, i) => {
			animations.push(animate(bond, [{ strokeDashoffset: '8', filter: 'drop-shadow(0 0 0px #ec4899)' }, { strokeDashoffset: '0', filter: 'drop-shadow(0 0 8px #ec4899)' }], { duration: 400, delay: 600 + i * 200, easing: 'ease-out' }));
		});
		labels.forEach((label, i) => {
			animations.push(animate(label, [{ opacity: 0, transform: 'scale(0.5)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 300, delay: 1000 + i * 150 }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-30px) skewX(-10deg)' }, { opacity: 1, transform: 'translateX(0) skewX(0)' }], { duration: 600, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 600 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.5)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 1200 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 01C - Deep Ocean (slower, flowing)
	peptideBondOcean: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'aminoAcidsOcean', header);
		const aminos = logo?.querySelectorAll('.amino') || [];
		const bonds = logo?.querySelectorAll('.bond') || [];
		const labels = logo?.querySelectorAll('.bond-label') || [];
		aminos.forEach((amino, i) => {
			animations.push(animate(amino, [
				{ opacity: 0, transform: 'scale(0) translateY(10px)' },
				{ opacity: 1, transform: 'scale(1) translateY(0)' }
			], { duration: 1200, delay: i * 600, easing: 'ease-out' }));
		});
		bonds.forEach((bond, i) => {
			animations.push(animate(bond, [{ strokeDashoffset: '8' }, { strokeDashoffset: '0' }], { duration: 1000, delay: 1800 + i * 600, easing: 'ease-in-out' }));
		});
		labels.forEach((label, i) => {
			animations.push(animate(label, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 3000 + i * 400 }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(15px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1200, delay: 600 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 1000, delay: 1400 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 3500 + i * 200 })));
		return animations.filter(Boolean);
	},

	// ===== 2. HELIX UNWIND SERIES =====
	
	// 02A - Original
	helixUnwind: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'basePairs', header);
		const strands = logo?.querySelectorAll('.strand') || [];
		const basePairs = logo?.querySelectorAll('.base-pair') || [];
		strands.forEach((strand, i) => {
			animations.push(animate(strand, [{ strokeDasharray: '200', strokeDashoffset: '200' }, { strokeDasharray: '200', strokeDashoffset: '0' }], { duration: 2000, delay: i * 200, easing: 'ease-out' }));
		});
		basePairs.forEach((bp, i) => {
			animations.push(animate(bp, [{ opacity: 0, transform: 'scaleX(0)' }, { opacity: 1, transform: 'scaleX(1)' }], { duration: 300, delay: 800 + i * 150, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' }));
		});
		if (logo) animations.push(animate(logo, [{ transform: 'rotateY(0deg)' }, { transform: 'rotateY(15deg)', offset: 0.25 }, { transform: 'rotateY(0deg)', offset: 0.5 }, { transform: 'rotateY(-15deg)', offset: 0.75 }, { transform: 'rotateY(0deg)' }], { duration: 4000, delay: 2000, iterations: Infinity, easing: 'ease-in-out' }));
		if (title) animations.push(animate(title, [{ opacity: 0, letterSpacing: '0.3em' }, { opacity: 1, letterSpacing: 'normal' }], { duration: 1000, delay: 500 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 1200 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 1800 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 02B - Crimson Code (fast, fiery)
	helixCrimson: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'basePairsFire', header);
		const strands = logo?.querySelectorAll('.strand') || [];
		const basePairs = logo?.querySelectorAll('.base-pair') || [];
		strands.forEach((strand, i) => {
			animations.push(animate(strand, [{ strokeDasharray: '200', strokeDashoffset: '200', filter: 'drop-shadow(0 0 0 #ef4444)' }, { strokeDasharray: '200', strokeDashoffset: '0', filter: 'drop-shadow(0 0 6px #ef4444)' }], { duration: 1200, delay: i * 100, easing: 'ease-out' }));
		});
		basePairs.forEach((bp, i) => {
			animations.push(animate(bp, [{ opacity: 0, transform: 'scaleX(0)', filter: 'brightness(2)' }, { opacity: 1, transform: 'scaleX(1)', filter: 'brightness(1)' }], { duration: 200, delay: 500 + i * 80, easing: 'ease-out' }));
		});
		if (logo) animations.push(animate(logo, [{ transform: 'rotateY(0deg)' }, { transform: 'rotateY(20deg)', offset: 0.25 }, { transform: 'rotateY(0deg)', offset: 0.5 }, { transform: 'rotateY(-20deg)', offset: 0.75 }, { transform: 'rotateY(0deg)' }], { duration: 2500, delay: 1200, iterations: Infinity, easing: 'ease-in-out' }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 600, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 700 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 1000 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 02C - Aurora (ethereal, slow)
	helixAurora: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'basePairsAurora', header);
		const strands = logo?.querySelectorAll('.strand') || [];
		const basePairs = logo?.querySelectorAll('.base-pair') || [];
		strands.forEach((strand, i) => {
			animations.push(animate(strand, [{ strokeDasharray: '200', strokeDashoffset: '200' }, { strokeDasharray: '200', strokeDashoffset: '0' }], { duration: 3000, delay: i * 400, easing: 'ease-out' }));
		});
		basePairs.forEach((bp, i) => {
			animations.push(animate(bp, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1500 + i * 250 }));
		});
		if (logo) animations.push(animate(logo, [{ transform: 'rotateY(0deg) scale(1)', filter: 'hue-rotate(0deg)' }, { transform: 'rotateY(10deg) scale(1.02)', filter: 'hue-rotate(30deg)', offset: 0.5 }, { transform: 'rotateY(0deg) scale(1)', filter: 'hue-rotate(0deg)' }], { duration: 6000, delay: 3000, iterations: Infinity, easing: 'ease-in-out' }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1500, delay: 800 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 1200, delay: 1800 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 2800 + i * 200 })));
		return animations.filter(Boolean);
	},

	// ===== 3. MOLECULAR ORBIT SERIES =====
	
	// 03A - Original
	molecularOrbit: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'particles', header);
		const nucleus = logo?.querySelector('.nucleus');
		const orbits = logo?.querySelectorAll('.orbit') || [];
		const electrons = logo?.querySelectorAll('.electron') || [];
		if (nucleus) {
			animations.push(animate(nucleus, [{ transform: 'scale(0)', filter: 'blur(10px)' }, { transform: 'scale(1.3)', filter: 'blur(0)', offset: 0.5 }, { transform: 'scale(1)', filter: 'blur(0)' }], { duration: 1000, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' }));
			animations.push(animate(nucleus, [{ transform: 'scale(1)', filter: 'drop-shadow(0 0 5px #8b5cf6)' }, { transform: 'scale(1.1)', filter: 'drop-shadow(0 0 10px #8b5cf6)', offset: 0.5 }, { transform: 'scale(1)', filter: 'drop-shadow(0 0 5px #8b5cf6)' }], { duration: 2000, delay: 1000, iterations: Infinity }));
		}
		orbits.forEach((orbit, i) => animations.push(animate(orbit, [{ opacity: 0, transform: `rotate(${i * 60} 25 25) scale(0.5)` }, { opacity: 0.5, transform: `rotate(${i * 60} 25 25) scale(1)` }], { duration: 800, delay: 500 + i * 200 })));
		electrons.forEach((electron, i) => animations.push(animate(electron, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: 1000 + i * 200 })));
		if (logo) animations.push(animate(logo, [{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], { duration: 10000, delay: 1500, iterations: Infinity, easing: 'linear' }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 800, delay: 600 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1200 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: 1500 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 03B - Solar Flare (intense, fast)
	orbitalSolar: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'particlesSolar', header);
		const nucleus = logo?.querySelector('.nucleus');
		const orbits = logo?.querySelectorAll('.orbit') || [];
		const electrons = logo?.querySelectorAll('.electron') || [];
		if (nucleus) {
			animations.push(animate(nucleus, [{ transform: 'scale(0)', filter: 'blur(15px) brightness(3)' }, { transform: 'scale(1.5)', filter: 'blur(0) brightness(1.5)', offset: 0.4 }, { transform: 'scale(1)', filter: 'blur(0) brightness(1)' }], { duration: 800, easing: 'ease-out' }));
			animations.push(animate(nucleus, [{ transform: 'scale(1)', filter: 'drop-shadow(0 0 8px #f59e0b)' }, { transform: 'scale(1.2)', filter: 'drop-shadow(0 0 20px #f59e0b)', offset: 0.5 }, { transform: 'scale(1)', filter: 'drop-shadow(0 0 8px #f59e0b)' }], { duration: 1500, delay: 800, iterations: Infinity }));
		}
		orbits.forEach((orbit, i) => animations.push(animate(orbit, [{ opacity: 0 }, { opacity: 0.6 }], { duration: 400, delay: 300 + i * 100 })));
		electrons.forEach((electron, i) => animations.push(animate(electron, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1.3)', offset: 0.6 }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 600 + i * 100 })));
		if (logo) animations.push(animate(logo, [{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], { duration: 6000, delay: 1000, iterations: Infinity, easing: 'linear' }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 500, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 600 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.5)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 900 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 03C - Ice Crystal (elegant, slow)
	orbitalIce: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'particlesIce', header);
		const nucleus = logo?.querySelector('.nucleus');
		const orbits = logo?.querySelectorAll('.orbit') || [];
		const electrons = logo?.querySelectorAll('.electron') || [];
		if (nucleus) {
			animations.push(animate(nucleus, [{ transform: 'scale(0)' }, { transform: 'scale(1)' }], { duration: 1500, easing: 'ease-out' }));
			animations.push(animate(nucleus, [{ filter: 'drop-shadow(0 0 3px #bae6fd)' }, { filter: 'drop-shadow(0 0 8px #bae6fd)', offset: 0.5 }, { filter: 'drop-shadow(0 0 3px #bae6fd)' }], { duration: 3000, delay: 1500, iterations: Infinity }));
		}
		orbits.forEach((orbit, i) => animations.push(animate(orbit, [{ opacity: 0 }, { opacity: 0.7 }], { duration: 1200, delay: 800 + i * 300 })));
		electrons.forEach((electron, i) => animations.push(animate(electron, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 800, delay: 1600 + i * 300 })));
		if (logo) animations.push(animate(logo, [{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], { duration: 20000, delay: 2500, iterations: Infinity, easing: 'linear' }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1200, delay: 1000 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 1000, delay: 1800 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 2500 + i * 200 })));
		return animations.filter(Boolean);
	},

	// ===== 4. LAB REACTION SERIES =====
	
	// 04A - Original
	labReaction: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'formulas', header);
		const flask = logo?.querySelector('.flask-body');
		const liquid = logo?.querySelector('.liquid');
		const bubbles = logo?.querySelectorAll('.bubble') || [];
		if (flask) animations.push(animate(flask, [{ strokeDasharray: '200', strokeDashoffset: '200' }, { strokeDasharray: '200', strokeDashoffset: '0' }], { duration: 1500, easing: 'ease-out' }));
		if (liquid) animations.push(animate(liquid, [{ transform: 'scaleY(0)', transformOrigin: 'bottom' }, { transform: 'scaleY(1)', transformOrigin: 'bottom' }], { duration: 1000, delay: 1000, easing: 'ease-out' }));
		bubbles.forEach((bubble, i) => {
			animations.push(animate(bubble, [{ opacity: 0, transform: 'translateY(0) scale(0.5)' }, { opacity: 0.8, transform: 'translateY(-5px) scale(1)', offset: 0.3 }, { opacity: 0.6, transform: 'translateY(-15px) scale(0.8)', offset: 0.7 }, { opacity: 0, transform: 'translateY(-25px) scale(0.3)' }], { duration: 2000, delay: 1500 + i * 300, iterations: Infinity }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-15px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 800, delay: 500 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1000 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: 2000 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 04B - Toxic (fast, aggressive)
	labToxic: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'formulasToxic', header);
		const flask = logo?.querySelector('.flask-body');
		const liquid = logo?.querySelector('.liquid');
		const bubbles = logo?.querySelectorAll('.bubble') || [];
		if (flask) animations.push(animate(flask, [{ strokeDasharray: '200', strokeDashoffset: '200' }, { strokeDasharray: '200', strokeDashoffset: '0' }], { duration: 800, easing: 'ease-out' }));
		if (liquid) animations.push(animate(liquid, [{ transform: 'scaleY(0)', transformOrigin: 'bottom', filter: 'brightness(1)' }, { transform: 'scaleY(1)', transformOrigin: 'bottom', filter: 'brightness(1.3)' }], { duration: 600, delay: 500, easing: 'ease-out' }));
		bubbles.forEach((bubble, i) => {
			animations.push(animate(bubble, [{ opacity: 0, transform: 'translateY(0) scale(0.3)' }, { opacity: 1, transform: 'translateY(-8px) scale(1.2)', offset: 0.2 }, { opacity: 0.8, transform: 'translateY(-20px) scale(0.8)', offset: 0.6 }, { opacity: 0, transform: 'translateY(-35px) scale(0.2)' }], { duration: 1200, delay: 800 + i * 150, iterations: Infinity }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 500, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 600 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.5)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 1000 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 04C - Sunset (gentle, warm)
	labSunset: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'formulasSunset', header);
		const flask = logo?.querySelector('.flask-body');
		const liquid = logo?.querySelector('.liquid');
		const bubbles = logo?.querySelectorAll('.bubble') || [];
		if (flask) animations.push(animate(flask, [{ strokeDasharray: '200', strokeDashoffset: '200' }, { strokeDasharray: '200', strokeDashoffset: '0' }], { duration: 2000, easing: 'ease-out' }));
		if (liquid) animations.push(animate(liquid, [{ transform: 'scaleY(0)', transformOrigin: 'bottom' }, { transform: 'scaleY(1)', transformOrigin: 'bottom' }], { duration: 1500, delay: 1500, easing: 'ease-out' }));
		bubbles.forEach((bubble, i) => {
			animations.push(animate(bubble, [{ opacity: 0, transform: 'translateY(0) scale(0.5)' }, { opacity: 0.6, transform: 'translateY(-3px) scale(0.9)', offset: 0.4 }, { opacity: 0.4, transform: 'translateY(-10px) scale(0.7)', offset: 0.8 }, { opacity: 0, transform: 'translateY(-15px) scale(0.4)' }], { duration: 3000, delay: 2500 + i * 500, iterations: Infinity }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1200, delay: 800 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 1000, delay: 1500 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 3000 + i * 200 })));
		return animations.filter(Boolean);
	},

	// ===== 5. SPECTRUM PEAKS SERIES =====
	
	// 05A - Original
	spectrumPeaks: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'dataStream', header);
		const peaks = logo?.querySelectorAll('.peak') || [];
		const labels = logo?.querySelectorAll('.peak-label') || [];
		peaks.forEach((peak, i) => {
			animations.push(animate(peak, [{ opacity: 0, transform: 'scaleY(0)', transformOrigin: 'bottom' }, { opacity: 1, transform: 'scaleY(1.1)', transformOrigin: 'bottom', offset: 0.7 }, { opacity: 1, transform: 'scaleY(1)', transformOrigin: 'bottom' }], { duration: 600, delay: 500 + i * 200, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' }));
		});
		labels.forEach((label, i) => animations.push(animate(label, [{ opacity: 0, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 400, delay: 1800 + i * 200 })));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 800, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 900 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'translateX(10px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 500, delay: 1500 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 05B - Electric (glitchy, sharp)
	spectrumElectric: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'dataStreamElectric', header);
		const peaks = logo?.querySelectorAll('.peak') || [];
		const labels = logo?.querySelectorAll('.peak-label') || [];
		peaks.forEach((peak, i) => {
			animations.push(animate(peak, [{ opacity: 0, transform: 'scaleY(0) translateX(-3px)', transformOrigin: 'bottom' }, { opacity: 1, transform: 'scaleY(1.2) translateX(3px)', transformOrigin: 'bottom', offset: 0.5 }, { opacity: 1, transform: 'scaleY(1) translateX(0)', transformOrigin: 'bottom' }], { duration: 400, delay: 300 + i * 100, easing: 'ease-out' }));
		});
		labels.forEach((label, i) => animations.push(animate(label, [{ opacity: 0 }, { opacity: 1 }], { duration: 200, delay: 900 + i * 100 })));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-15px) skewX(-5deg)' }, { opacity: 1, transform: 'translateX(0) skewX(0)' }], { duration: 500, delay: 200 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 500 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 300, delay: 800 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 05C - Infrared (pulsing, thermal)
	spectrumInfrared: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'dataStreamInfrared', header);
		const peaks = logo?.querySelectorAll('.peak') || [];
		const labels = logo?.querySelectorAll('.peak-label') || [];
		peaks.forEach((peak, i) => {
			animations.push(animate(peak, [{ opacity: 0, transform: 'scaleY(0)', transformOrigin: 'bottom' }, { opacity: 1, transform: 'scaleY(1)', transformOrigin: 'bottom' }], { duration: 800, delay: 600 + i * 250, easing: 'ease-out' }));
			animations.push(animate(peak, [{ filter: 'brightness(1)' }, { filter: 'brightness(1.3)', offset: 0.5 }, { filter: 'brightness(1)' }], { duration: 2000, delay: 1400 + i * 250, iterations: Infinity }));
		});
		labels.forEach((label, i) => animations.push(animate(label, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 2200 + i * 200 })));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1000, delay: 400 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 1000 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1800 + i * 150 })));
		return animations.filter(Boolean);
	},

	// ===== 6. PROTEIN FOLD SERIES =====
	
	// 06A - Original
	proteinFold: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'hBonds', header);
		const chain = logo?.querySelector('.protein-chain');
		const hBonds = logo?.querySelectorAll('.h-bond') || [];
		if (chain) {
			animations.push(animate(chain, [{ strokeDasharray: '300', strokeDashoffset: '300' }, { strokeDasharray: '300', strokeDashoffset: '0' }], { duration: 2500, easing: 'ease-out' }));
			animations.push(animate(chain, [{ transform: 'scaleX(1.2) scaleY(0.8)' }, { transform: 'scaleX(1) scaleY(1)', offset: 0.5 }, { transform: 'scaleX(0.95) scaleY(1.05)' }], { duration: 2000, delay: 2500, easing: 'ease-in-out' }));
		}
		hBonds.forEach((hb, i) => {
			animations.push(animate(hb, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1.5)', offset: 0.6 }, { opacity: 0.8, transform: 'scale(1)' }], { duration: 600, delay: 3000 + i * 300 }));
			animations.push(animate(hb, [{ opacity: 0.8, transform: 'scale(1)' }, { opacity: 1, transform: 'scale(1.2)', offset: 0.5 }, { opacity: 0.8, transform: 'scale(1)' }], { duration: 1500, delay: 3600 + i * 300, iterations: Infinity }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 800, delay: 500 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1200 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: 2000 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 06B - Mint (crisp, clean)
	proteinMint: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'hBondsMint', header);
		const chain = logo?.querySelector('.protein-chain');
		const hBonds = logo?.querySelectorAll('.h-bond') || [];
		if (chain) {
			animations.push(animate(chain, [{ strokeDasharray: '300', strokeDashoffset: '300' }, { strokeDasharray: '300', strokeDashoffset: '0' }], { duration: 1800, easing: 'ease-out' }));
		}
		hBonds.forEach((hb, i) => {
			animations.push(animate(hb, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 1800 + i * 200 }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-15px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 600, delay: 400 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 800 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 1400 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 06C - Twilight (mystical, glowing)
	proteinTwilight: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'hBondsTwilight', header);
		const chain = logo?.querySelector('.protein-chain');
		const hBonds = logo?.querySelectorAll('.h-bond') || [];
		if (chain) {
			animations.push(animate(chain, [{ strokeDasharray: '300', strokeDashoffset: '300', filter: 'drop-shadow(0 0 0 #d946ef)' }, { strokeDasharray: '300', strokeDashoffset: '0', filter: 'drop-shadow(0 0 8px #d946ef)' }], { duration: 3000, easing: 'ease-out' }));
		}
		hBonds.forEach((hb, i) => {
			animations.push(animate(hb, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1.5)', offset: 0.5 }, { opacity: 0.9, transform: 'scale(1)' }], { duration: 800, delay: 3000 + i * 400 }));
			animations.push(animate(hb, [{ filter: 'drop-shadow(0 0 3px #f5d0fe)' }, { filter: 'drop-shadow(0 0 10px #f5d0fe)', offset: 0.5 }, { filter: 'drop-shadow(0 0 3px #f5d0fe)' }], { duration: 2500, delay: 3800 + i * 400, iterations: Infinity }));
		});
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(15px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1200, delay: 800 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 1000, delay: 1600 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 2500 + i * 200 })));
		return animations.filter(Boolean);
	},

	// ===== 7. MEMBRANE FLOW SERIES =====
	
	// 07A - Original
	membraneFlow: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'lipids', header);
		const lipidHeads = logo?.querySelectorAll('.lipid-head') || [];
		const molecule = logo?.querySelector('.passing-molecule');
		lipidHeads.forEach((head, i) => {
			animations.push(animate(head, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: i * 100, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' }));
			animations.push(animate(head, [{ transform: 'translateX(0)' }, { transform: 'translateX(1px)', offset: 0.25 }, { transform: 'translateX(0)', offset: 0.5 }, { transform: 'translateX(-1px)', offset: 0.75 }, { transform: 'translateX(0)' }], { duration: 2000, delay: 1000 + i * 100, iterations: Infinity, easing: 'ease-in-out' }));
		});
		if (molecule) animations.push(animate(molecule, [{ transform: 'translateX(0)', opacity: 1 }, { transform: 'translateX(-20px)', opacity: 0.8, offset: 0.3 }, { transform: 'translateX(-35px)', opacity: 0.5, offset: 0.5 }, { transform: 'translateX(-50px)', opacity: 0.8, offset: 0.7 }, { transform: 'translateX(-70px)', opacity: 1 }], { duration: 3000, delay: 1500, iterations: Infinity }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-15px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 800, delay: 400 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1000 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: 1500 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 07B - Golden Gate
	membraneGold: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'lipidsGold', header);
		const lipidHeads = logo?.querySelectorAll('.lipid-head') || [];
		const molecule = logo?.querySelector('.passing-molecule');
		lipidHeads.forEach((head, i) => {
			animations.push(animate(head, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1.1)', offset: 0.6 }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: i * 80, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' }));
		});
		if (molecule) animations.push(animate(molecule, [{ transform: 'translateX(0)', opacity: 1, filter: 'brightness(1)' }, { transform: 'translateX(-35px)', opacity: 0.7, filter: 'brightness(1.5)', offset: 0.5 }, { transform: 'translateX(-70px)', opacity: 1, filter: 'brightness(1)' }], { duration: 2500, delay: 1000, iterations: Infinity }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 600, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 700 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 1100 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 07C - Deep Sea
	membraneDeep: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'lipidsDeep', header);
		const lipidHeads = logo?.querySelectorAll('.lipid-head') || [];
		const molecule = logo?.querySelector('.passing-molecule');
		lipidHeads.forEach((head, i) => {
			animations.push(animate(head, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 600, delay: i * 150, easing: 'ease-out' }));
			animations.push(animate(head, [{ filter: 'drop-shadow(0 0 2px #3b82f6)' }, { filter: 'drop-shadow(0 0 6px #22d3ee)', offset: 0.5 }, { filter: 'drop-shadow(0 0 2px #3b82f6)' }], { duration: 3000, delay: 1200 + i * 150, iterations: Infinity }));
		});
		if (molecule) animations.push(animate(molecule, [{ transform: 'translateX(0)', opacity: 1 }, { transform: 'translateX(-70px)', opacity: 1 }], { duration: 4000, delay: 2000, iterations: Infinity, easing: 'ease-in-out' }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1000, delay: 600 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 1200 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1800 + i * 150 })));
		return animations.filter(Boolean);
	},

	// ===== 8. CRYSTAL LATTICE SERIES =====
	
	// 08A - Original
	crystalLattice: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'lattice', header);
		const nodes = logo?.querySelectorAll('.node') || [];
		const lines = logo?.querySelectorAll('.lattice-line') || [];
		const nodeOrder = [4, 1, 3, 5, 7, 0, 2, 6, 8];
		nodes.forEach((node, i) => {
			const order = nodeOrder.indexOf(i);
			animations.push(animate(node, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1.3)', offset: 0.6 }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: order * 150, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)' }));
		});
		lines.forEach((line, i) => animations.push(animate(line, [{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay: 1200 + i * 50 })));
		const centerNode = nodes[4];
		if (centerNode) animations.push(animate(centerNode, [{ filter: 'drop-shadow(0 0 3px #c7d2fe)' }, { filter: 'drop-shadow(0 0 8px #c7d2fe)', offset: 0.5 }, { filter: 'drop-shadow(0 0 3px #c7d2fe)' }], { duration: 2000, delay: 2000, iterations: Infinity }));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 800, delay: 500 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1100 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: 1800 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 08B - Ruby Matrix
	crystalRuby: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'latticeRuby', header);
		const nodes = logo?.querySelectorAll('.node') || [];
		const lines = logo?.querySelectorAll('.lattice-line') || [];
		nodes.forEach((node, i) => {
			animations.push(animate(node, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1.2)', offset: 0.5 }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: i * 80, easing: 'ease-out' }));
			animations.push(animate(node, [{ filter: 'brightness(1)' }, { filter: 'brightness(1.5)', offset: 0.5 }, { filter: 'brightness(1)' }], { duration: 2000, delay: 800 + i * 80, iterations: Infinity }));
		});
		lines.forEach((line, i) => animations.push(animate(line, [{ opacity: 0 }, { opacity: 1 }], { duration: 200, delay: 700 + i * 30 })));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-15px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 600, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 700 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 1200 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 08C - Diamond Clear
	crystalDiamond: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'latticeDiamond', header);
		const nodes = logo?.querySelectorAll('.node') || [];
		const lines = logo?.querySelectorAll('.lattice-line') || [];
		nodes.forEach((node, i) => {
			animations.push(animate(node, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 600, delay: i * 120, easing: 'ease-out' }));
		});
		lines.forEach((line, i) => animations.push(animate(line, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 1100 + i * 60 })));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1000, delay: 600 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 1200 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1800 + i * 150 })));
		return animations.filter(Boolean);
	},

	// ===== 9. FLUORESCENT SCAN SERIES =====
	
	// 09A - Original
	fluorescentScan: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'uvSweep', header);
		const molecules = logo?.querySelectorAll('.fluoro-mol') || [];
		const glows = logo?.querySelectorAll('.glow') || [];
		molecules.forEach((mol, i) => animations.push(animate(mol, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: i * 100 })));
		glows.forEach((glow, i) => animations.push(animate(glow, [{ opacity: 0 }, { opacity: 0, offset: 0.3 }, { opacity: 0.8, offset: 0.5 }, { opacity: 0.4, offset: 0.7 }, { opacity: 0 }], { duration: 3000, delay: 1000 + i * 400, iterations: Infinity })));
		molecules.forEach((mol, i) => animations.push(animate(mol, [{ fill: '#365314' }, { fill: '#365314', offset: 0.3 }, { fill: '#84cc16', offset: 0.5 }, { fill: '#65a30d', offset: 0.7 }, { fill: '#365314' }], { duration: 3000, delay: 1000 + i * 400, iterations: Infinity })));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 800, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 900 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 500, delay: 1500 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 09B - Blacklight Party
	fluorescentParty: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'uvSweepParty', header);
		const molecules = logo?.querySelectorAll('.fluoro-mol') || [];
		const glows = logo?.querySelectorAll('.glow') || [];
		molecules.forEach((mol, i) => animations.push(animate(mol, [{ opacity: 0, transform: 'scale(0) rotate(-90deg)' }, { opacity: 1, transform: 'scale(1.2) rotate(0)', offset: 0.6 }, { opacity: 1, transform: 'scale(1) rotate(0)' }], { duration: 300, delay: i * 60 })));
		glows.forEach((glow, i) => animations.push(animate(glow, [{ opacity: 0 }, { opacity: 1, offset: 0.4 }, { opacity: 0.6, offset: 0.6 }, { opacity: 0 }], { duration: 2000, delay: 600 + i * 250, iterations: Infinity })));
		molecules.forEach((mol, i) => animations.push(animate(mol, [{ fill: '#581c87' }, { fill: '#e879f9', offset: 0.4 }, { fill: '#f472b6', offset: 0.6 }, { fill: '#581c87' }], { duration: 2000, delay: 600 + i * 250, iterations: Infinity })));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-25px) skewX(-5deg)' }, { opacity: 1, transform: 'translateX(0) skewX(0)' }], { duration: 500, delay: 200 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 500 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.5)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 800 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 09C - Bioluminescence
	fluorescentBio: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'uvSweepBio', header);
		const molecules = logo?.querySelectorAll('.fluoro-mol') || [];
		const glows = logo?.querySelectorAll('.glow') || [];
		molecules.forEach((mol, i) => animations.push(animate(mol, [{ opacity: 0, transform: 'scale(0)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 600, delay: i * 150 })));
		glows.forEach((glow, i) => animations.push(animate(glow, [{ opacity: 0 }, { opacity: 0.6, offset: 0.5 }, { opacity: 0 }], { duration: 4000, delay: 1200 + i * 500, iterations: Infinity })));
		molecules.forEach((mol, i) => animations.push(animate(mol, [{ fill: '#164e63' }, { fill: '#22d3ee', offset: 0.5 }, { fill: '#164e63' }], { duration: 4000, delay: 1200 + i * 500, iterations: Infinity })));
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1000, delay: 500 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 1100 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 1800 + i * 150 })));
		return animations.filter(Boolean);
	},

	// ===== 10. DATA EXTRACT SERIES =====
	
	// 10A - Original
	dataExtract: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'documents', header);
		const docOutline = logo?.querySelector('.doc-outline');
		const textLines = logo?.querySelectorAll('.text-line') || [];
		const highlights = logo?.querySelectorAll('.highlight') || [];
		const arrow = logo?.querySelector('.extract-arrow');
		if (docOutline) animations.push(animate(docOutline, [{ strokeDasharray: '200', strokeDashoffset: '200' }, { strokeDasharray: '200', strokeDashoffset: '0' }], { duration: 1000, easing: 'ease-out' }));
		textLines.forEach((line, i) => animations.push(animate(line, [{ opacity: 0, transform: 'scaleX(0)', transformOrigin: 'left' }, { opacity: 1, transform: 'scaleX(1)', transformOrigin: 'left' }], { duration: 400, delay: 800 + i * 150 })));
		highlights.forEach((hl, i) => animations.push(animate(hl, [{ opacity: 0 }, { opacity: 0, offset: 0.2 }, { opacity: 0.6, offset: 0.4 }, { opacity: 0.6, offset: 0.6 }, { opacity: 0, offset: 0.8 }, { opacity: 0 }], { duration: 4000, delay: 2000 + i * 500, iterations: Infinity })));
		if (arrow) {
			animations.push(animate(arrow, [{ opacity: 0, transform: 'translateX(-10px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 500, delay: 2500 }));
			animations.push(animate(arrow, [{ transform: 'translateX(0)' }, { transform: 'translateX(3px)', offset: 0.5 }, { transform: 'translateX(0)' }], { duration: 1000, delay: 3000, iterations: Infinity }));
		}
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-15px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 800, delay: 300 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 900 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'translateX(10px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 500, delay: 1500 + i * 150 })));
		return animations.filter(Boolean);
	},

	// 10B - Matrix Code
	dataMatrix: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'documentsMatrix', header);
		const docOutline = logo?.querySelector('.doc-outline');
		const textLines = logo?.querySelectorAll('.text-line') || [];
		const highlights = logo?.querySelectorAll('.highlight') || [];
		const arrow = logo?.querySelector('.extract-arrow');
		if (docOutline) animations.push(animate(docOutline, [{ strokeDasharray: '200', strokeDashoffset: '200' }, { strokeDasharray: '200', strokeDashoffset: '0' }], { duration: 600, easing: 'ease-out' }));
		textLines.forEach((line, i) => animations.push(animate(line, [{ opacity: 0 }, { opacity: 1 }], { duration: 200, delay: 400 + i * 80 })));
		highlights.forEach((hl, i) => animations.push(animate(hl, [{ opacity: 0 }, { opacity: 0.8, offset: 0.3 }, { opacity: 0.8, offset: 0.7 }, { opacity: 0 }], { duration: 2500, delay: 1000 + i * 300, iterations: Infinity })));
		if (arrow) {
			animations.push(animate(arrow, [{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay: 1200 }));
			animations.push(animate(arrow, [{ transform: 'translateX(0)' }, { transform: 'translateX(5px)', offset: 0.5 }, { transform: 'translateX(0)' }], { duration: 600, delay: 1500, iterations: Infinity }));
		}
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateX(-20px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 500, delay: 200 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 500 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0, transform: 'scale(0.8)' }, { opacity: 1, transform: 'scale(1)' }], { duration: 400, delay: 900 + i * 100 })));
		return animations.filter(Boolean);
	},

	// 10C - Blueprint
	dataBlueprint: (header) => {
		const { logo, title, subtitle, badges } = collectElements(header);
		const animations = [];
		startCanvasAnimation(header.querySelector('.topbar-bg-canvas'), 'documentsBlueprint', header);
		const docOutline = logo?.querySelector('.doc-outline');
		const textLines = logo?.querySelectorAll('.text-line') || [];
		const highlights = logo?.querySelectorAll('.highlight') || [];
		const arrow = logo?.querySelector('.extract-arrow');
		if (docOutline) animations.push(animate(docOutline, [{ strokeDasharray: '200', strokeDashoffset: '200' }, { strokeDasharray: '200', strokeDashoffset: '0' }], { duration: 1500, easing: 'ease-out' }));
		textLines.forEach((line, i) => animations.push(animate(line, [{ opacity: 0, transform: 'scaleX(0)', transformOrigin: 'left' }, { opacity: 1, transform: 'scaleX(1)', transformOrigin: 'left' }], { duration: 600, delay: 1200 + i * 200 })));
		highlights.forEach((hl, i) => animations.push(animate(hl, [{ opacity: 0 }, { opacity: 0.4, offset: 0.5 }, { opacity: 0 }], { duration: 5000, delay: 2500 + i * 600, iterations: Infinity })));
		if (arrow) {
			animations.push(animate(arrow, [{ opacity: 0, transform: 'translateX(-15px)' }, { opacity: 1, transform: 'translateX(0)' }], { duration: 800, delay: 3500 }));
		}
		if (title) animations.push(animate(title, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 1000, delay: 500 }));
		if (subtitle) animations.push(animate(subtitle, [{ opacity: 0 }, { opacity: 1 }], { duration: 800, delay: 1100 }));
		badges.forEach((badge, i) => animations.push(animate(badge, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 2000 + i * 150 })));
		return animations.filter(Boolean);
	},
};

// -- Controller --

const startAnimation = (header) => {
	const variantName = header.dataset.topbarAnim;
	const variant = variants[variantName];
	if (!variant) return;
	stopAnimations(header);
	const animations = variant(header) || [];
	activeAnimations.set(header, animations);
};

const restartAnimation = (header) => {
	stopAnimations(header);
	requestAnimationFrame(() => startAnimation(header));
};

const startAllAnimations = () => {
	document.querySelectorAll('[data-topbar-anim]').forEach((header) => startAnimation(header));
};

const wireReplayButtons = () => {
	document.querySelectorAll('[data-topbar-replay]').forEach((button) => {
		button.addEventListener('click', () => {
			const card = button.closest('.topbar-demo-card');
			if (!card) return;
			const header = card.querySelector('[data-topbar-anim]');
			if (!header) return;
			restartAnimation(header);
		});
	});
};

// Export
window.TopbarAnimations = {
	startAll: startAllAnimations,
	start: startAnimation,
	stop: stopAnimations,
	restart: restartAnimation,
};

document.addEventListener('DOMContentLoaded', () => {
	startAllAnimations();
	wireReplayButtons();
});
