const fs = require('fs');

// Capture a Chrome DevTools trace while playing the Mandelbrot path.
// Run with: npx -p playwright@latest node scripts/capture_mandelbrot_trace.js
(async () => {
  const { chromium } = require('playwright');

  const browser = await chromium.launch({
    headless: true,
    args: ['--disable-features=CalculateNativeWinOcclusion']
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const client = await context.newCDPSession(page);

  // Collect timeline + CPU profiler events.
  await client.send('Tracing.start', {
    categories: [
      'devtools.timeline',
      'disabled-by-default-devtools.timeline',
      'disabled-by-default-v8.cpu_profiler',
      'blink.user_timing',
      'latencyInfo'
    ].join(','),
    options: 'sampling-frequency=10000',
    transferMode: 'ReturnAsStream'
  });

  await page.goto('http://localhost:8000/frontend/index.html', { waitUntil: 'networkidle' });
  await page.waitForSelector('#dataset-select');
  await page.selectOption('#dataset-select', 'mandelbrot_single_precision');
  await page.waitForTimeout(500);

  // Play the camera path.
  await page.click('#btn-play-pause');
  await page.waitForTimeout(51_000); // Path duration is ~50s; add a buffer.

  await client.send('Tracing.end');
  const tracingComplete = await new Promise(resolve => client.once('Tracing.tracingComplete', resolve));
  const { stream } = tracingComplete;

  const chunks = [];
  while (true) {
    const { data, eof } = await client.send('IO.read', { handle: stream });
    chunks.push(data);
    if (eof) break;
  }
  await client.send('IO.close', { handle: stream });

  const tracePath = 'artifacts/mandelbrot_trace.json';
  fs.writeFileSync(tracePath, chunks.join(''));
  console.log(`Trace written to ${tracePath}`);

  await browser.close();
})();
