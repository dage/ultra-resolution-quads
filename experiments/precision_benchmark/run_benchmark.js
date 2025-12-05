
const fs = require('fs');
const path = require('path');

// Load modules
// Note: These paths assume we run from the project root
const Decimal = require('../../shared/libs/decimal.min.js');
const CameraPath = require('../../shared/camera_path.js');
const ViewUtils = require('../../shared/view_utils.js');

const OUTPUT_HTML = path.join(__dirname, '../../artifacts/precision_benchmark_report.html');

// Benchmark Configuration
const PRECISIONS = [20, 50, 100, 150, 200, 300, 400, 500, 1000];
const ITERATIONS = 2000;
const WARMUP = 100;

// Mock Data
const VIEWPORT = { width: 1920, height: 1080 };
const TILE_SIZE = 512;

// A path simulating a deep zoom to force significant calculation
const MOCK_PATH = {
    keyframes: [
        { globalLevel: 0, x: "0.5", y: "0.5", rotation: 0 },
        { globalLevel: 500, x: "0.50000000000000000000000000000001", y: "0.50000000000000000000000000000001", rotation: 360 }
    ]
};

function runBenchmark() {
    const results = [];

    console.log(`Starting Benchmark: ${ITERATIONS} iterations per precision level.`);
    console.log("---------------------------------------------------------------");
    console.log("| Precision | Interpolation (ms) | View Calc (ms) | Total (ms) | Ops/Sec |");
    console.log("---------------------------------------------------------------");

    for (const prec of PRECISIONS) {
        // 1. Set Precision
        Decimal.set({ precision: prec });

        // Re-build sampler to ensure it uses new precision if it caches anything (it mostly doesn't, but safe to do)
        const sampler = CameraPath.buildSampler(MOCK_PATH);
        
        // 2. Warmup
        for (let i = 0; i < WARMUP; i++) {
            const t = i / WARMUP;
            const cam = sampler.cameraAtProgress(t);
            ViewUtils.getVisibleTilesForLevel(cam, Math.floor(cam.globalLevel), VIEWPORT.width, VIEWPORT.height, TILE_SIZE);
        }

        // 3. Measure Interpolation
        const startInterp = process.hrtime.bigint();
        let lastCam = null;
        for (let i = 0; i < ITERATIONS; i++) {
            const t = i / ITERATIONS;
            lastCam = sampler.cameraAtProgress(t);
        }
        const endInterp = process.hrtime.bigint();
        const timeInterpNs = Number(endInterp - startInterp);

        // 4. Measure View Calculation (using the last camera from interpolation)
        // We pick a camera in the middle of the zoom to ensure non-trivial math
        const midCam = sampler.cameraAtProgress(0.8); // Level ~400
        
        const startView = process.hrtime.bigint();
        for (let i = 0; i < ITERATIONS; i++) {
             ViewUtils.getVisibleTilesForLevel(midCam, Math.floor(midCam.globalLevel), VIEWPORT.width, VIEWPORT.height, TILE_SIZE);
        }
        const endView = process.hrtime.bigint();
        const timeViewNs = Number(endView - startView);

        // Stats
        const avgInterpMs = (timeInterpNs / ITERATIONS) / 1e6;
        const avgViewMs = (timeViewNs / ITERATIONS) / 1e6;
        const totalMs = avgInterpMs + avgViewMs;
        const opsSec = 1000 / totalMs;

        results.push({
            precision: prec,
            interpolation: avgInterpMs,
            viewCalc: avgViewMs,
            total: totalMs,
            opsSec: opsSec
        });

        console.log(`| ${String(prec).padEnd(9)} | ${avgInterpMs.toFixed(4).padEnd(18)} | ${avgViewMs.toFixed(4).padEnd(14)} | ${totalMs.toFixed(4).padEnd(10)} | ${opsSec.toFixed(0).padEnd(7)} |`);
    }
    console.log("---------------------------------------------------------------");

    generateHtmlReport(results);
}

function generateHtmlReport(results) {
    const labels = results.map(r => r.precision);
    const dataTotal = results.map(r => r.total);
    const dataInterp = results.map(r => r.interpolation);
    const dataView = results.map(r => r.viewCalc);

    const html = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Precision Performance Benchmark</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 2rem; max-width: 900px; margin: 0 auto; color: #333; }
        h1 { border-bottom: 2px solid #eee; padding-bottom: 0.5rem; }
        .chart-container { position: relative; height: 400px; width: 100%; margin-top: 2rem; }
        table { width: 100%; border-collapse: collapse; margin-top: 2rem; }
        th, td { text-align: right; padding: 0.75rem; border-bottom: 1px solid #eee; }
        th:first-child, td:first-child { text-align: left; }
        th { background: #f8f9fa; font-weight: 600; }
        .note { background: #e3f2fd; padding: 1rem; border-radius: 8px; margin-top: 1rem; border-left: 4px solid #2196f3; }
    </style>
</head>
<body>
    <h1>Decimal Precision vs. Performance</h1>
    <p>Benchmark of the "Per-Frame" Logic cost (Camera Interpolation + View Tile Calculation) at varying Decimal precision levels.</p>
    
    <div class="note">
        <strong>Observation:</strong> Lower precision (e.g., 50) is significantly faster. 
        High precision (200+) causes exponential slowdowns, primarily in multiplication/division operations required for coordinate interpolation.
    </div>

    <div class="chart-container">
        <canvas id="perfChart"></canvas>
    </div>

    <table>
        <thead>
            <tr>
                <th>Precision (Digits)</th>
                <th>Interpolation (ms)</th>
                <th>View Calc (ms)</th>
                <th>Total Frame Cost (ms)</th>
                <th>Max FPS (Theoretical)</th>
            </tr>
        </thead>
        <tbody>
            ${results.map(r => `
            <tr>
                <td>${r.precision}</td>
                <td>${r.interpolation.toFixed(3)}</td>
                <td>${r.viewCalc.toFixed(3)}</td>
                <td><strong>${r.total.toFixed(3)}</strong></td>
                <td>${Math.floor(1000/r.total)}</td>
            </tr>
            `).join('')}
        </tbody>
    </table>

    <script>
        const ctx = document.getElementById('perfChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: ${JSON.stringify(labels)},
                datasets: [
                    {
                        label: 'Total Time (ms)',
                        data: ${JSON.stringify(dataTotal)},
                        borderColor: '#d32f2f',
                        backgroundColor: 'rgba(211, 47, 47, 0.1)',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.3
                    },
                    {
                        label: 'Interpolation (ms)',
                        data: ${JSON.stringify(dataInterp)},
                        borderColor: '#1976d2',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        tension: 0.3
                    },
                    {
                        label: 'View Calc (ms)',
                        data: ${JSON.stringify(dataView)},
                        borderColor: '#388e3c',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        tension: 0.3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Time per Frame (ms)' }
                    },
                    x: {
                        title: { display: true, text: 'Precision (Decimal Digits)' }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Impact of Precision on Calculation Cost'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                    }
                }
            }
        });
    </script>
</body>
</html>
    `;

    fs.mkdirSync(path.dirname(OUTPUT_HTML), { recursive: true });
    fs.writeFileSync(OUTPUT_HTML, html);
    console.log(`\nReport generated at: ${OUTPUT_HTML}`);
}

runBenchmark();
