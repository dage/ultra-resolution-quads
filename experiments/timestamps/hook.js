// Define a container for our data
window.telemetryData = [];

// Define the hook that runs every frame
window.externalLoopHook = function(state, now) {
    // Only collect data when the camera path is actually playing
    if (state.experience.active) {
        // Record a high-precision timestamp
        window.telemetryData.push(now);
    }
};
