import argparse
import subprocess
import sys
import json
import os
import time
from playwright.sync_api import sync_playwright

def run_experiment(dataset, hook_file, output_file, visible=False, port=8015):
    # 1. Read the Custom JavaScript Hook
    try:
        with open(hook_file, 'r') as f:
            custom_js = f.read()
    except FileNotFoundError:
        print(f"Error: Hook file '{hook_file}' not found.")
        return

    # 2. Start the HTTP Server
    print(f"Starting HTTP server on port {port}...")
    cwd = os.getcwd()
    server_process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=cwd 
    )
    time.sleep(2) # Wait for server

    try:
        with sync_playwright() as p:
            print(f"Launching browser (Headless: {not visible})...")
            browser = p.chromium.launch(headless=not visible)
            # Set viewport to match backend generation default (1920x1080)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            
            # Enable console logging from the browser with type/location for easier debugging
            page.on("console", lambda msg: print(f"BROWSER_CONSOLE[{msg.type.upper()}] {msg.text} ({msg.location.get('url','')}:{msg.location.get('lineNumber','')})"))
            page.on("pageerror", lambda exc: print(f"BROWSER_ERROR: {exc}"))

            # 3. Inject the Custom Hook
            # We prepend a safety check to ensure telemetryData exists if the user didn't define it
            init_script = f"""
                window.telemetryData = window.telemetryData || [];
                {custom_js}
            """
            page.add_init_script(init_script)

            # 4. Navigate
            url = f"http://localhost:{port}/frontend/index.html?dataset={dataset}&autoplay=true"
            print(f"Navigating to {url}")
            page.goto(url)
            # Wait for app to be ready enough to expose appState
            page.wait_for_function("window.appState !== undefined", timeout=30000)
            
            # 5. Wait for Start (Autoplay)
            print("Waiting for experience to start...")
            try:
                page.wait_for_function("window.appState && window.appState.experience.active === true", timeout=60000)
                print("Experience started!")
            except Exception as e:
                print("Timed out waiting for start. (Check dataset/autoplay)")
                raise e

            # 6. Wait for End
            print("Running experience...")
            # Wait until active becomes false
            page.wait_for_function("window.appState.experience.active === false", timeout=300000) # 5 min max
            print("Experience finished!")

            # 7. Extract Data
            page.evaluate("""
                if (!window.telemetryData) window.telemetryData = [];
                if (typeof window.emitTextContentTelemetryNow === 'function') {
                    try { window.emitTextContentTelemetryNow(); } catch (e) { console.error(e); }
                }
                window.telemetryData;
            """)
            print("Extracting 'window.telemetryData'...")
            data = page.evaluate("window.telemetryData")
            
            # 8. Save to File
            # Create directory if needed
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)
            print(f"Data saved to: {output_file}")
            print(f"Collected {len(data)} records.")

            browser.close()

    except Exception as e:
        print(f"Experiment failed: {e}")
    finally:
        server_process.terminate()
        server_process.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a browser-based experiment with custom JS injection.")
    parser.add_argument("--dataset", required=True, help="Dataset ID to load")
    parser.add_argument("--hook", required=True, help="Path to the .js file containing window.externalLoopHook")
    parser.add_argument("--output", required=True, help="Path to save the collected window.telemetryData (JSON)")
    parser.add_argument("--visible", action="store_true", help="Run with a visible browser window (not headless)")
    
    args = parser.parse_args()
    
    run_experiment(args.dataset, args.hook, args.output, visible=args.visible)
