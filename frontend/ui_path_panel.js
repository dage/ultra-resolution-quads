class PathPanel {
    constructor(container) {
        this.container = container;
        this.listEl = document.createElement('div');
        this.listEl.className = 'path-list';
        this.container.appendChild(this.listEl);
        
        this.callbacks = {
            onJump: null,
            onDelete: null,
            onAdd: null,
            onCopy: null
        };

        // Create Controls Area (Add / Copy)
        this.controlsEl = document.createElement('div');
        this.controlsEl.className = 'path-controls';
        this.controlsEl.style.display = 'flex';
        this.controlsEl.style.gap = '10px';
        this.controlsEl.style.marginTop = '10px';

        const btnAdd = document.createElement('button');
        btnAdd.className = 'icon-btn';
        btnAdd.textContent = '＋';
        btnAdd.title = 'Add Keyframe (Current View)';
        btnAdd.onclick = () => this.callbacks.onAdd?.();

        const btnCopy = document.createElement('button');
        btnCopy.className = 'icon-btn';
        btnCopy.textContent = '⧉';
        btnCopy.title = 'Copy Path JSON';
        btnCopy.onclick = (e) => this.callbacks.onCopy?.(e.target);

        this.controlsEl.appendChild(btnAdd);
        this.controlsEl.appendChild(btnCopy);
        this.container.appendChild(this.controlsEl);
    }

    onJump(cb) { this.callbacks.onJump = cb; }
    onDelete(cb) { this.callbacks.onDelete = cb; }
    onAdd(cb) { this.callbacks.onAdd = cb; }
    onCopy(cb) { this.callbacks.onCopy = cb; }

    render(keyframes) {
        this.listEl.innerHTML = '';
        if (!keyframes || keyframes.length === 0) {
            this.listEl.innerHTML = '<div style="color: #666; font-style: italic; font-size: 0.9em; padding: 5px;">No keyframes</div>';
            return;
        }

        keyframes.forEach((kf, index) => {
            const row = document.createElement('div');
            row.className = 'keyframe-item';
            row.dataset.index = index;

            // Info (Level + Note)
            const cam = kf.camera || kf;
            const lvl = typeof cam.globalLevel === 'number' ? cam.globalLevel.toFixed(1) : '?';
            const info = document.createElement('span');
            info.className = 'keyframe-info';
            info.textContent = `#${index + 1} (L${lvl})`;
            info.title = `Level: ${cam.globalLevel}\nX: ${cam.x}\nY: ${cam.y}`;
            
            // Click to Jump
            info.onclick = () => this.callbacks.onJump?.(index);

            // Delete Button
            const btnDel = document.createElement('button');
            btnDel.className = 'delete-btn';
            btnDel.textContent = '×';
            btnDel.title = 'Delete Keyframe';
            btnDel.onclick = (e) => {
                e.stopPropagation();
                this.callbacks.onDelete?.(index);
            };

            row.appendChild(info);
            row.appendChild(btnDel);
            this.listEl.appendChild(row);
        });
    }

    setActive(index) {
        const items = this.listEl.querySelectorAll('.keyframe-item');
        items.forEach(el => el.classList.remove('active'));
        if (index >= 0 && index < items.length) {
            items[index].classList.add('active');
            items[index].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }
}

// Expose to window
window.PathPanel = PathPanel;
