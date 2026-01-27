/**
 * State management module - manages application state.
 */

/**
 * Create a simple observable state store.
 */
export function createStore(initialState = {}) {
    let state = { ...initialState };
    const listeners = new Set();
    
    return {
        get(key) {
            return key !== undefined ? state[key] : { ...state };
        },
        
        set(updates) {
            const prevState = state;
            state = { ...state, ...updates };
            listeners.forEach(fn => fn(state, prevState));
        },
        
        subscribe(listener) {
            listeners.add(listener);
            return () => listeners.delete(listener);
        },
    };
}

// Default application state
const defaultState = {
    // Provider info
    provider: 'openai',
    model: null,
    selectedProvider: 'openai',

    // Prompt selection
    prompts: [],
    activePromptId: null,
    selectedPromptId: null,
    
    // Search state
    searchQuery: '',
    searchResults: [],
    isSearching: false,
    
    // Batch selection state
    selectedPapers: new Map(), // pdf_url -> paper item
    
    // Papers table state (unified view)
    papers: [],
    queueStats: { queued: 0, processing: 0 },
    
    // Drawer state
    drawerOpen: false,
    drawerPaperId: null,
    drawerPaper: null,
    drawerRuns: [],
    resolvedRunSources: {},
};

// Global app store
export const appStore = createStore(defaultState);

// --- Search Actions ---

export function setSearchResults(results) {
    appStore.set({
        searchResults: Array.isArray(results) ? results : [],
        isSearching: false,
    });
}

export function setSearching(isSearching) {
    appStore.set({ isSearching });
}

// --- Batch Selection Actions ---

export function togglePaperSelection(paper) {
    const selected = new Map(appStore.get('selectedPapers'));
    const key = paper.pdf_url || paper.url;
    
    if (selected.has(key)) {
        selected.delete(key);
    } else {
        selected.set(key, paper);
    }
    
    appStore.set({ selectedPapers: selected });
}

export function clearBatchSelection() {
    appStore.set({ selectedPapers: new Map() });
}

export function setSelectedPapers(selected) {
    const map = selected instanceof Map ? selected : new Map();
    appStore.set({ selectedPapers: map });
}

export function getSelectedPapers() {
    return Array.from(appStore.get('selectedPapers').values());
}

export function isPaperSelected(paper) {
    const key = paper.pdf_url || paper.url;
    return appStore.get('selectedPapers').has(key);
}

// --- Provider Actions ---

export function setSelectedProvider(provider) {
    appStore.set({ selectedProvider: provider });
}

export function getSelectedProvider() {
    return appStore.get('selectedProvider');
}

// --- Prompt Actions ---

export function setPrompts(prompts, activePromptId = null) {
    appStore.set({
        prompts: Array.isArray(prompts) ? prompts : [],
        activePromptId,
    });
}

export function setSelectedPrompt(promptId) {
    appStore.set({ selectedPromptId: promptId });
}

export function getSelectedPrompt() {
    return appStore.get('selectedPromptId');
}

// --- Papers Table Actions ---

export function setPapers(papers, queueStats = null) {
    const updates = { papers: Array.isArray(papers) ? papers : [] };
    if (queueStats) {
        updates.queueStats = queueStats;
    }
    appStore.set(updates);
}

export function updatePaperStatus(paperId, runId, status, failureReason = null) {
    const papers = appStore.get('papers').map(p => {
        if (p.id === paperId) {
            return {
                ...p,
                latest_run_id: runId,
                status: status,
                failure_reason: failureReason,
            };
        }
        return p;
    });
    appStore.set({ papers });
}

export function addPaperToList(paper) {
    const papers = appStore.get('papers');
    // Check if paper already exists
    const existing = papers.find(p => p.id === paper.id);
    if (existing) {
        // Update existing
        appStore.set({
            papers: papers.map(p => p.id === paper.id ? { ...p, ...paper } : p),
        });
    } else {
        // Add to beginning
        appStore.set({ papers: [paper, ...papers] });
    }
}

// --- Drawer Actions ---

export function openDrawer(paperId) {
    appStore.set({
        drawerOpen: true,
        drawerPaperId: paperId,
    });
}

export function closeDrawer() {
    appStore.set({
        drawerOpen: false,
        drawerPaperId: null,
        drawerPaper: null,
        drawerRuns: [],
    });
}

export function setDrawerContent(paper, runs) {
    appStore.set({
        drawerPaper: paper,
        drawerRuns: runs,
    });
}
