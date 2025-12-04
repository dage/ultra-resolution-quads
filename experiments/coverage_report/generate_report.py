import json
import argparse
import os
from collections import defaultdict

def generate_report(data_file, output_html):
    try:
        with open(data_file, 'r') as f:
            events = json.load(f)
    except FileNotFoundError:
        print(f"Error: Data file '{data_file}' not found.")
        return

    # Process events to track state per tile
    tiles = {} # tileId -> { level, x, y, requested_time, loaded_time, first_visible_time, max_opacity }
    
    for event in events:
        tile_id = event.get('tileId')
        if not tile_id: continue
        
        if tile_id not in tiles:
            tiles[tile_id] = {
                'id': tile_id,
                'level': event.get('level'),
                'x': event.get('x'),
                'y': event.get('y'),
                'requested': False,
                'loaded': False,
                'visible': False,
                'max_opacity': 0.0
            }
        
        t = tiles[tile_id]
        if event['type'] == 'requested':
            t['requested'] = True
        elif event['type'] == 'loaded':
            t['loaded'] = True
        elif event['type'] == 'visible':
            t['visible'] = True
            t['max_opacity'] = max(t['max_opacity'], event.get('opacity', 0))

    total_requested = len(tiles)
    visible_tiles = [t for t in tiles.values() if t['visible']]
    loaded_not_visible = [t for t in tiles.values() if t['loaded'] and not t['visible']]
    requested_not_loaded = [t for t in tiles.values() if t['requested'] and not t['loaded']]
    
    # Group by Level
    level_stats = defaultdict(lambda: {'total': 0, 'visible': 0, 'loaded_unused': 0})
    for t in tiles.values():
        lvl = t['level']
        level_stats[lvl]['total'] += 1
        if t['visible']:
            level_stats[lvl]['visible'] += 1
        elif t['loaded']:
            level_stats[lvl]['loaded_unused'] += 1

    # HTML Generation
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Tile Coverage Analysis</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f4f4f9; color: #333; }}
            h1, h2 {{ color: #2c3e50; }}
            .container {{ max_width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
            .card {{ background: #fff; padding: 20px; border-radius: 8px; border: 1px solid #e0e0e0; text-align: center; }}
            .card h3 {{ margin: 0 0 10px 0; font-size: 1.1em; color: #7f8c8d; }}
            .card .value {{ font-size: 2em; font-weight: bold; color: #2c3e50; }}
            .card .sub {{ font-size: 0.9em; color: #95a5a6; }}
            
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            th, td {{ border: 1px solid #eee; padding: 12px 15px; text-align: left; }}
            th {{ background-color: #f8f9fa; font-weight: 600; color: #2c3e50; }}
            tr:nth-child(even) {{ background-color: #fcfcfc; }}
            tr:hover {{ background-color: #f1f1f1; }}
            
            .bar-container {{ width: 100%; background-color: #ecf0f1; height: 24px; position: relative; border-radius: 4px; overflow: hidden; }}
            .bar-visible {{ height: 100%; background-color: #27ae60; float: left; }}
            .bar-unused {{ height: 100%; background-color: #e74c3c; float: left; }}
            
            .legend {{ margin-bottom: 10px; font-size: 0.9em; }}
            .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Tile Coverage Analysis Report</h1>
            <p>Dataset: <strong>exp_coverage_ds</strong></p>
            
            <div class="summary-grid">
                <div class="card">
                    <h3>Total Requested</h3>
                    <div class="value">{total_requested}</div>
                    <div class="sub">Tiles</div>
                </div>
                <div class="card">
                    <h3>Actually Visible</h3>
                    <div class="value">{len(visible_tiles)}</div>
                    <div class="sub">{len(visible_tiles)/total_requested:.1%} Utilization</div>
                </div>
                <div class="card">
                    <h3>Loaded but Unused</h3>
                    <div class="value">{len(loaded_not_visible)}</div>
                    <div class="sub">{len(loaded_not_visible)/total_requested:.1%} Waste</div>
                </div>
            </div>

            <h2>Level Breakdown</h2>
            <div class="legend">
                <span class="dot" style="background: #27ae60;"></span>Visible
                <span class="dot" style="background: #e74c3c; margin-left: 15px;"></span>Loaded but Unused
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Level</th>
                        <th>Total</th>
                        <th>Visible</th>
                        <th>Unused</th>
                        <th>Utilization Bar</th>
                    </tr>
                </thead>
                <tbody>
    """

    sorted_levels = sorted(level_stats.keys())
    for lvl in sorted_levels:
        stats = level_stats[lvl]
        total = stats['total']
        vis = stats['visible']
        unused = stats['loaded_unused']
        
        vis_pct = (vis / total * 100) if total > 0 else 0
        unused_pct = (unused / total * 100) if total > 0 else 0

        html += f"""
                <tr>
                    <td>{lvl}</td>
                    <td>{total}</td>
                    <td>{vis}</td>
                    <td>{unused}</td>
                    <td style="width: 40%;">
                        <div class="bar-container">
                            <div class="bar-visible" style="width: {vis_pct}%;" title="Visible: {vis}"></div>
                            <div class="bar-unused" style="width: {unused_pct}%;" title="Unused: {unused}"></div>
                        </div>
                    </td>
                </tr>
        """

    html += """
                </tbody>
            </table>
            
            <h2>Unused Tiles (Sample)</h2>
            <div style="max-height: 300px; overflow-y: auto; border: 1px solid #eee; padding: 10px;">
                <code>
    """
    
    for t in loaded_not_visible:
        html += f"{t['id']} (Level {t['level']})<br>"

    html += """
                </code>
            </div>
        </div>
    </body>
    </html>
    """

    with open(output_html, 'w') as f:
        f.write(html)
    
    print(f"Report generated: {output_html}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    generate_report(args.data, args.output)
