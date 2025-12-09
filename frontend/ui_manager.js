class UIManager {
    constructor(state, callbacks = {}) {
        this.state = state;
        this.callbacks = callbacks;
        this.els = {
            viewer: document.getElementById('viewer'),
            layers: document.getElementById('layers-container'),
            datasetSelect: document.getElementById('dataset-select'),
            chkDebug: document.getElementById('chk-debug'),
            chkLiveRender: document.getElementById('chk-live-render'),
            queueStatus: document.getElementById('queue-status'),
            queueText: document.getElementById('queue-text'),
            queueDot: document.querySelector('#queue-status .status-dot'),
            inputs: {
                level: document.getElementById('in-level'),
                x: document.getElementById('in-x'),
                y: document.getElementById('in-y'),
                rotation: document.getElementById('in-rot'),
                time: document.getElementById('in-time'),
            },
            vals: {
                level: document.getElementById('val-level'),
                x: document.getElementById('val-x'),
                y: document.getElementById('val-y'),
                rotation: document.getElementById('val-rot'),
            },
            debugStats: document.getElementById('debug-stats'),
            experienceControls: document.getElementById('experience-controls'),
            btns: {
                start: document.getElementById('btn-skip-start'),
                back: document.getElementById('btn-skip-back'),
                playPause: document.getElementById('btn-play-pause'),
                fwd: document.getElementById('btn-skip-fwd'),
                end: document.getElementById('btn-skip-end')
            },
            btnFullscreen: document.getElementById('btn-fullscreen'),
            btnToggleUI: document.getElementById('btn-toggle-ui'),
            btnAddKeyframe: document.getElementById('btn-add-keyframe'),
            btnCopyKeyframes: document.getElementById('btn-copy-keyframes'),
            valKeyframeCount: document.getElementById('val-keyframe-count'),
            app: document.getElementById('app')
        };

        this.LOG10_2 = Math.log10 ? Math.log10(2) : Math.LOG10E * Math.LN2;
    }

    init() {
        this.setupEventListeners();
        this.updateToggleIcon();
        this.updateCursor();

        // Initialize Path Panel
        const pathContainer = document.getElementById('path-panel-container');
        if (pathContainer && window.PathPanel) {
            this.pathPanel = new PathPanel(pathContainer);
            
            this.pathPanel.onJump((index) => {
                this.callbacks.onPathJump?.(index);
            });
            
            this.pathPanel.onAdd(() => {
                this.callbacks.onPathAdd?.();
            });
            
            this.pathPanel.onDelete((index) => {
                this.callbacks.onPathDelete?.(index);
            });

            this.pathPanel.onCopy((btn) => {
                this.callbacks.onPathCopy?.(btn);
            });
        }
    }

    updatePathList(keyframes) {
        if (this.pathPanel) {
            this.pathPanel.render(keyframes);
        }
    }

    updatePathActive(index) {
        if (this.pathPanel) {
            this.pathPanel.setActive(index);
        }
    }

    updateQueueStatus({ pending, activeLive, backend }) {
        if (!this.els.queueText) return;

        const backendActive = backend && backend.active_renders > 0;
        const backendUp = backend && backend.up;
        const progress = backend && backend.progress;

        if (activeLive > 0 || backendActive) {
            if (progress) {
                this.els.queueText.textContent = `Rendering ${progress} (${pending} pending)`;
            } else {
                this.els.queueText.textContent = `Rendering... (${pending} pending)`;
            }
        } else if (pending > 0) {
            this.els.queueText.textContent = `Queued (${pending})`;
        } else if (backendUp) {
            this.els.queueText.textContent = "Idle";
        } else {
            this.els.queueText.textContent = "Backend unavailable";
        }

        if (this.els.queueDot) {
            if (backendActive || activeLive > 0) this.els.queueDot.classList.add('active');
            else this.els.queueDot.classList.remove('active');
        }
    }

    setupEventListeners() {
        const { state, els } = this;
        const cb = this.callbacks;

        if (els.datasetSelect) {
            els.datasetSelect.addEventListener('change', (e) => cb.onDatasetChange?.(e.target.value));
        }

        if (els.chkDebug) {
            els.chkDebug.addEventListener('change', (e) => {
                if (e.target.checked) {
                    document.body.classList.add('debug');
                } else {
                    document.body.classList.remove('debug');
                }
            });
        }

        if (els.chkLiveRender) {
            els.chkLiveRender.addEventListener('change', (e) => {
                state.liveRender = e.target.checked;
                if (state.liveRender) {
                    if (els.queueStatus) els.queueStatus.classList.remove('hidden');
                    cb.onLiveRenderToggle?.(true);
                } else {
                    cb.onLiveRenderToggle?.(false);
                    state.backendStatus = null;
                    if (els.queueStatus) els.queueStatus.classList.add('hidden');
                }
            });
        }

        if (els.btns.playPause) {
            els.btns.playPause.addEventListener('click', () => {
                if (!state.activePath) return;

                if (state.experience.active) {
                    state.experience.active = false;
                    els.btns.playPause.textContent = '▶';
                } else {
                    if (state.experience.currentElapsed >= state.experience.totalDuration) {
                        state.experience.currentElapsed = 0;
                    }

                    state.experience.active = true;
                    state.experience.startTime = performance.now() - state.experience.currentElapsed;
                    els.btns.playPause.textContent = '⏸';
                }
                this.updateInputAvailability();
            });
        }

        if (els.btns.start) {
            els.btns.start.addEventListener('click', () => {
                state.experience.currentElapsed = 0;
                if (state.experience.active) state.experience.startTime = performance.now();
                cb.onUpdateExperience?.(state.experience.active ? performance.now() : 0);
                if (!state.experience.active) cb.onForceSeek?.(0);
                this.updateInputAvailability();
            });
        }

        if (els.btns.end) {
            els.btns.end.addEventListener('click', () => {
                state.experience.currentElapsed = state.experience.totalDuration;
                state.experience.active = false;
                if (els.btns.playPause) els.btns.playPause.textContent = '▶';
                cb.onForceSeek?.(state.experience.totalDuration);
                this.updateInputAvailability();
            });
        }

        if (els.btns.back) {
            els.btns.back.addEventListener('click', () => {
                let t = state.experience.currentElapsed - 10000;
                if (t < 0) t = 0;
                state.experience.currentElapsed = t;
                if (state.experience.active) state.experience.startTime = performance.now() - t;
                else cb.onForceSeek?.(t);
                this.updateInputAvailability();
            });
        }

        if (els.btns.fwd) {
            els.btns.fwd.addEventListener('click', () => {
                let t = state.experience.currentElapsed + 10000;
                if (t > state.experience.totalDuration) t = state.experience.totalDuration;
                state.experience.currentElapsed = t;
                if (state.experience.active) state.experience.startTime = performance.now() - t;
                else cb.onForceSeek?.(t);
                this.updateInputAvailability();
            });
        }

        if (els.inputs.time) {
            els.inputs.time.addEventListener('input', (e) => {
                state.experience.active = false;
                if (els.btns.playPause) els.btns.playPause.textContent = '▶';

                const scrubbedFraction = parseFloat(e.target.value);
                const scrubbedTime = state.experience.totalDuration * scrubbedFraction;

                state.experience.currentElapsed = scrubbedTime;
                cb.onForceSeek?.(scrubbedTime);
                this.updateInputAvailability();
            });
        }

        if (els.viewer) {
            els.viewer.addEventListener('mousedown', (e) => {
                if (e.target.closest('button') || e.target.closest('.control-btn')) return;

                state.isDragging = true;
                state.lastMouse = { x: e.clientX, y: e.clientY };
            });
        }

        window.addEventListener('mouseup', () => state.isDragging = false);

        window.addEventListener('mousemove', (e) => {
            if (!state.isDragging) return;

            if (state.experience.active) {
                state.experience.active = false;
                if (els.btns.playPause) els.btns.playPause.textContent = '▶';
                this.updateInputAvailability();
            }

            const dx = e.clientX - state.lastMouse.x;
            const dy = e.clientY - state.lastMouse.y;
            state.lastMouse = { x: e.clientX, y: e.clientY };

            cb.onPan?.(dx, dy);
        });

        if (els.viewer) {
            els.viewer.addEventListener('wheel', (e) => {
                e.preventDefault();

                if (state.experience.active) {
                    state.experience.active = false;
                    if (els.btns.playPause) els.btns.playPause.textContent = '▶';
                    this.updateInputAvailability();
                }

                cb.onZoom?.(-e.deltaY * 0.002);
            }, { passive: false });
        }

        if (els.inputs.level) {
            els.inputs.level.addEventListener('input', (e) => {
                const lvl = parseInt(e.target.value);
                if (!Number.isNaN(lvl)) {
                    state.camera.globalLevel = Math.max(0, lvl);
                    this.update();
                }
            });
        }

        if (els.inputs.x) {
            els.inputs.x.addEventListener('input', (e) => {
                try {
                    const next = this.callbacks.onClampDecimal?.(e.target.value);
                    if (next !== undefined && next !== null) {
                        state.camera.x = next;
                        this.update();
                    }
                } catch (err) {}
            });
        }

        if (els.inputs.y) {
            els.inputs.y.addEventListener('input', (e) => {
                try {
                    const next = this.callbacks.onClampDecimal?.(e.target.value);
                    if (next !== undefined && next !== null) {
                        state.camera.y = next;
                        this.update();
                    }
                } catch (err) {}
            });
        }

        if (els.inputs.rotation) {
            els.inputs.rotation.addEventListener('input', (e) => {
                state.camera.rotation = parseFloat(e.target.value);
                this.update();
            });
        }

        window.addEventListener('keydown', (e) => {
            if (e.code === 'Space') {
                e.preventDefault();
                if (els.btns.playPause) els.btns.playPause.click();
            }
            if (e.code === 'Escape') {
                e.preventDefault();
                if (els.btnToggleUI) els.btnToggleUI.click();
            }
        });

        if (els.btnAddKeyframe) {
            els.btnAddKeyframe.addEventListener('click', () => {
                const kf = {
                    camera: {
                        globalLevel: state.camera.globalLevel,
                        globalX: state.camera.x.toString(),
                        globalY: state.camera.y.toString(),
                        rotation: state.camera.rotation || 0,
                        note: `Keyframe ${state.capturedKeyframes.length + 1}`
                    }
                };
                state.capturedKeyframes.push(kf);
                if (els.valKeyframeCount) {
                    els.valKeyframeCount.textContent = `(${state.capturedKeyframes.length})`;
                }
                console.log("Keyframe added:", kf);
            });
        }

        if (els.btnCopyKeyframes) {
            els.btnCopyKeyframes.addEventListener('click', () => {
                const json = JSON.stringify(state.capturedKeyframes, null, 2);
                if (navigator.clipboard) {
                    navigator.clipboard.writeText(json).then(() => {
                        console.log("Keyframes copied to clipboard.");
                        const originalText = els.btnCopyKeyframes.textContent;
                        els.btnCopyKeyframes.textContent = "✓";
                        setTimeout(() => els.btnCopyKeyframes.textContent = originalText, 1000);
                    }).catch(err => console.error("Clipboard failed:", err));
                } else {
                    console.log("Clipboard API unavailable. Keyframes:", json);
                }
            });
        }

        this.updateInputAvailability();
    }

    update() {
        const { state, els } = this;
        if (!els.vals.level) return;
        const lvl = Math.floor(state.camera.globalLevel);
        const zoomOffset = state.camera.globalLevel - lvl;
        const posDigits = this.positionPrecision(state.camera.globalLevel);
        els.vals.level.textContent = `${lvl} (+ ${zoomOffset.toFixed(3)})`;
        if (els.vals.x) els.vals.x.textContent = state.camera.x.toFixed(posDigits);
        if (els.vals.y) els.vals.y.textContent = state.camera.y.toFixed(posDigits);
        if (els.vals.rotation) els.vals.rotation.textContent = (state.camera.rotation || 0).toFixed(3);

        if (document.activeElement !== els.inputs.level) els.inputs.level.value = lvl;
        if (document.activeElement !== els.inputs.x) els.inputs.x.value = state.camera.x.toFixed(posDigits);
        if (document.activeElement !== els.inputs.y) els.inputs.y.value = state.camera.y.toFixed(posDigits);
        if (document.activeElement !== els.inputs.rotation) els.inputs.rotation.value = (state.camera.rotation || 0).toFixed(3);
    }

    updateInputAvailability() {
        const { state, els } = this;
        const disabled = !!state.experience.active;
        els.inputs.level.disabled = disabled;
        els.inputs.x.disabled = disabled;
        els.inputs.y.disabled = disabled;
        els.inputs.rotation.disabled = disabled;

        if (els.experienceControls) {
            els.experienceControls.style.display = 'block';
        }
    }

    updateCursor() {
        const { els } = this;
        if (!els.viewer) return;
        els.viewer.classList.remove('explore', 'experience');
        els.viewer.classList.add('explore');
    }

    updateToggleIcon() {
        const { els } = this;
        if (!els.btnToggleUI) return;
        const isCollapsed = els.app.classList.contains('ui-collapsed');
        const svg = els.btnToggleUI.querySelector('svg');
            if (svg) {
                if (isCollapsed) {
                    svg.innerHTML = '<path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"/>';
                    els.btnToggleUI.title = "Show UI Panel";
                } else {
                    svg.innerHTML = '<path d="M4 18h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v8c0 1.1.9 2 2 2zm0-10h16v8H4V8z"/>';
                    els.btnToggleUI.title = "Hide UI Panel";
                }
            }
        }

    positionPrecision(level) {
        const levelDigits = Math.ceil(Math.max(0, level) * this.LOG10_2);
        return Math.max(6, Math.min(50, levelDigits + 3));
    }
}

window.UIManager = UIManager;
