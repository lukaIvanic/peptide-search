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
    selectedModel: '',
    providerCatalog: [],

    // Prompt selection
    prompts: [],
    activePromptId: null,
    selectedPromptId: null,
    
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

// --- Provider Actions ---

export function setSelectedProvider(provider) {
    appStore.set({ selectedProvider: provider });
}

export function getSelectedProvider() {
    return appStore.get('selectedProvider');
}

export function setSelectedModel(model) {
    appStore.set({ selectedModel: model || '' });
}

export function getSelectedModel() {
    return appStore.get('selectedModel') || '';
}

export function setProviderCatalog(catalog) {
    appStore.set({ providerCatalog: Array.isArray(catalog) ? catalog : [] });
}

export function getProviderCatalog() {
    return appStore.get('providerCatalog') || [];
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
