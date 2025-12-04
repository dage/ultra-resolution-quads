self.onmessage = async function(e) {
    const { id, url } = e.data;
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const blob = await response.blob();
        // Load full resolution
        const bitmap = await createImageBitmap(blob);
        
        self.postMessage({ id, bitmap }, [bitmap]);
    } catch (error) {
        self.postMessage({ id, error: error.message });
    }
};
