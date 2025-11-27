"""
Continuity check for camera paths using the simplified camera API.
Samples camera_at_progress at a fine delta, computes position deltas,
velocity/acceleration/delta-acceleration ("jerk"), and reports:
- Boundary discontinuities (L/R of each keyframe)
- Strongest spikes anywhere on the path with their progress p in [0,1] and nearest keyframe index.

Usage:
    python experiments/path_continuity_check.py \
        --dataset mandelbrot_deep \
        [--path-id default_path] \
        [--samples 20000] \
        [--window 0.002] \
        [--vel-thresh 0.05] \
        [--accel-thresh 0.25] \
        [--jerk-factor 50]
"""

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from backend import camera_utils  # noqa: E402


def load_paths(dataset_id: str):
    path_file = ROOT / "datasets" / dataset_id / "paths.json"
    data = json.loads(path_file.read_text())
    return data.get("paths", [])


def cam_to_vec(cam, zoom_weight=100.0):
    lvl = cam['level'] + cam.get('zoomOffset', 0.0)
    scale = 2 ** lvl
    gx = (cam['tileX'] + cam['offsetX']) / (2 ** cam['level'])
    gy = (cam['tileY'] + cam['offsetY']) / (2 ** cam['level'])
    return (gx * scale, gy * scale, zoom_weight * lvl)


def central_diff(values, dt):
    n = len(values)
    out = [(0.0, 0.0, 0.0)] * n
    if n < 3:
        return out
    for i in range(1, n - 1):
        out[i] = tuple((values[i + 1][j] - values[i - 1][j]) / (2 * dt) for j in range(3))
    out[0] = out[1]
    out[-1] = out[-2]
    return out


def magnitude(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def find_spikes(mags, progresses, median, factor, top_k=10, boundaries=None, boundary_to_idx=None):
    spikes = []
    if median <= 0:
        return spikes
    for m, p in zip(mags, progresses):
        ratio = m / median if median > 0 else 0
        if ratio > factor:
            nearest = None
            nearest_idx = None
            if boundaries:
                nearest = min((abs(p - b), b) for b in boundaries)[1]
                if boundary_to_idx and nearest in boundary_to_idx:
                    nearest_idx = boundary_to_idx[nearest]
            spikes.append((ratio, m, p, nearest, nearest_idx))
    spikes.sort(key=lambda x: x[0], reverse=True)
    return spikes[:top_k]


def analyze_path(path, samples, window, vel_thresh, accel_thresh, jerk_factor, spike_factor, dump=False):
    camera_utils.set_camera_path(path, internal_resolution=max(samples, 2000), tension=0.0)
    progress_vals = [i / (samples - 1) for i in range(samples)]
    cameras = camera_utils.cameras_at_progresses(progress_vals)
    positions = [cam_to_vec(cam) for cam in cameras]

    dt = 1.0 / (samples - 1)
    velocities = central_diff(positions, dt)
    accelerations = central_diff(velocities, dt)
    jerks = central_diff(accelerations, dt)

    num_segments = max(1, len(path.get('keyframes', [])) - 1)
    boundaries = [i / num_segments for i in range(1, num_segments)]
    boundary_to_idx = {b: i for i, b in enumerate(boundaries, start=1)}

    issues = {"velocity": [], "acceleration": [], "jerk": [], "spikes": {}}

    for b in boundaries:
        left = [magnitude(velocities[i]) for i, p in enumerate(progress_vals) if b - window <= p < b and i > 0]
        right = [magnitude(velocities[i]) for i, p in enumerate(progress_vals) if b <= p <= b + window and i < samples - 1]
        left_a = [magnitude(accelerations[i]) for i, p in enumerate(progress_vals) if b - window <= p < b and i > 0]
        right_a = [magnitude(accelerations[i]) for i, p in enumerate(progress_vals) if b <= p <= b + window and i < samples - 1]

        if left and right:
            lv = sum(left) / len(left)
            rv = sum(right) / len(right)
            jump = abs(lv - rv) / max(1e-9, max(lv, rv))
            if jump > vel_thresh:
                issues["velocity"].append((b, jump, lv, rv))

        if left_a and right_a:
            la = sum(left_a) / len(left_a)
            ra = sum(right_a) / len(right_a)
            jump = abs(la - ra) / max(1e-9, max(la, ra))
            if jump > accel_thresh:
                issues["acceleration"].append((b, jump, la, ra))

    vel_mag = [magnitude(v) for v in velocities]
    acc_mag = [magnitude(a) for a in accelerations]
    jerk_mag = [magnitude(j) for j in jerks]
    pos_step_mag = []
    for i in range(1, len(positions)):
        prev = positions[i - 1]
        cur = positions[i]
        dx = cur[0] - prev[0]
        dy = cur[1] - prev[1]
        dz = cur[2] - prev[2]
        pos_step_mag.append(math.sqrt(dx * dx + dy * dy + dz * dz))

    med_pos = statistics.median(pos_step_mag) if pos_step_mag else 0
    med_vel = statistics.median(vel_mag) if vel_mag else 0
    med_acc = statistics.median(acc_mag) if acc_mag else 0
    med_jerk = statistics.median(jerk_mag) if jerk_mag else 0

    spikes_pos = find_spikes(pos_step_mag, progress_vals[1:], med_pos, spike_factor, boundaries=boundaries, boundary_to_idx=boundary_to_idx)
    spikes_vel = find_spikes(vel_mag, progress_vals, med_vel, spike_factor, boundaries=boundaries, boundary_to_idx=boundary_to_idx)
    spikes_acc = find_spikes(acc_mag, progress_vals, med_acc, spike_factor, boundaries=boundaries, boundary_to_idx=boundary_to_idx)
    spikes_jerk = find_spikes(jerk_mag, progress_vals, med_jerk, jerk_factor, boundaries=boundaries, boundary_to_idx=boundary_to_idx)

    issues["spikes"] = {
        "position": spikes_pos,
        "velocity": spikes_vel,
        "acceleration": spikes_acc,
        "jerk": spikes_jerk,
        "medians": {
            "position": med_pos,
            "velocity": med_vel,
            "acceleration": med_acc,
            "jerk": med_jerk
        }
    }

    return issues, {
        "progress": progress_vals,
        "positions": positions,
        "vel_mag": vel_mag,
        "acc_mag": acc_mag,
        "jerk_mag": jerk_mag,
        "pos_step_mag": pos_step_mag,
        "cameras": cameras,
    }


def main():
    parser = argparse.ArgumentParser(description="Check camera path continuity (velocity/acceleration/delta-acceleration).")
    parser.add_argument("--dataset", default="mandelbrot_deep")
    parser.add_argument("--path-id", default=None)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--window", type=float, default=0.002)
    parser.add_argument("--vel-thresh", type=float, default=0.05)
    parser.add_argument("--accel-thresh", type=float, default=0.25)
    parser.add_argument("--jerk-factor", type=float, default=50.0)
    parser.add_argument("--spike-factor", type=float, default=20.0, help="Median multiplier to report spikes for pos/vel/acc.")
    parser.add_argument("--dump", action="store_true", help="If set, output raw per-sample magnitudes after the results.")
    args = parser.parse_args()

    paths = load_paths(args.dataset)
    if args.path_id:
        paths = [p for p in paths if p.get("id") == args.path_id]
        if not paths:
            raise SystemExit(f"No path '{args.path_id}' in dataset '{args.dataset}'")
    if not paths:
        raise SystemExit(f"No paths found in dataset '{args.dataset}'")

    any_fail = False
    last_dump_data = None
    for path in paths:
        issues, dump_data = analyze_path(path, args.samples, args.window, args.vel_thresh, args.accel_thresh, args.jerk_factor, args.spike_factor, dump=args.dump)
        last_dump_data = dump_data
        name = path.get("name") or path.get("id") or "<unnamed>"
        print(f"\nPath: {name}")
        has_spike_vel = bool(issues["spikes"]["velocity"])
        has_spike_acc = bool(issues["spikes"]["acceleration"])
        has_spike_jerk = bool(issues["spikes"]["jerk"])
        has_spike_pos = bool(issues["spikes"]["position"])

        # Boundary checks (keyframe neighborhoods)
        if issues["velocity"]:
            any_fail = True
            print("  ⚠ Velocity boundary jumps:")
            for b, jump, lv, rv in issues["velocity"]:
                print(f"    at keyframe t={b:.4f} jump={jump*100:.1f}% (left={lv:.4f}, right={rv:.4f})")
        else:
            print("  ✓ No velocity boundary jumps.")

        if issues["acceleration"]:
            any_fail = True
            print("  ⚠ Acceleration boundary jumps:")
            for b, jump, la, ra in issues["acceleration"]:
                print(f"    at keyframe t={b:.4f} jump={jump*100:.1f}% (left={la:.4f}, right={ra:.4f})")
        else:
            print("  ✓ No acceleration boundary jumps.")

        # Global spike summaries (override any “OK” impression)
        if has_spike_vel:
            any_fail = True
            print("  ⚠ Velocity spikes detected (see list below).")
        if has_spike_acc:
            any_fail = True
            print("  ⚠ Acceleration spikes detected (see list below).")
        if has_spike_jerk:
            any_fail = True
            med = issues["spikes"]["medians"]["jerk"]
            peak = max(m for _, m, _, _, _ in issues["spikes"]["jerk"])
            print(f"  ⚠ Delta-acceleration spikes detected: max/median = {peak/med:.1f}x (max={peak:.2e}, median={med:.2e})")
        else:
            print("  ✓ No large delta-acceleration spikes.")

        spikes = issues["spikes"]
        if spikes["position"]:
            any_fail = True
            print("  ⚠ Position spikes (top):")
            for ratio, mag, prog, near, near_idx in spikes["position"]:
                where = f"p={prog:.4f}"
                if near_idx is not None:
                    where += f" (nearest keyframe #{near_idx})"
                elif near is not None:
                    where += f" (nearest keyframe at p={near:.4f})"
                print(f"    {where} ratio={ratio:.1f}x mag={mag:.4e}")
        if spikes["velocity"]:
            any_fail = True
            print("  ⚠ Velocity spikes (top):")
            for ratio, mag, prog, near, near_idx in spikes["velocity"]:
                where = f"p={prog:.4f}"
                if near_idx is not None:
                    where += f" (nearest keyframe #{near_idx})"
                elif near is not None:
                    where += f" (nearest keyframe at p={near:.4f})"
                print(f"    {where} ratio={ratio:.1f}x mag={mag:.4e}")
        if spikes["acceleration"]:
            any_fail = True
            print("  ⚠ Acceleration spikes (top):")
            for ratio, mag, prog, near, near_idx in spikes["acceleration"]:
                where = f"p={prog:.4f}"
                if near_idx is not None:
                    where += f" (nearest keyframe #{near_idx})"
                elif near is not None:
                    where += f" (nearest keyframe at p={near:.4f})"
                print(f"    {where} ratio={ratio:.1f}x mag={mag:.4e}")
        if spikes["jerk"]:
            any_fail = True
            print("  ⚠ Delta-acceleration spikes (top):")
            for ratio, mag, prog, near, near_idx in spikes["jerk"]:
                where = f"p={prog:.4f}"
                if near_idx is not None:
                    where += f" (nearest keyframe #{near_idx})"
                elif near is not None:
                    where += f" (nearest keyframe at p={near:.4f})"
                print(f"    {where} ratio={ratio:.1f}x mag={mag:.4e}")

    if args.dump and last_dump_data is not None:
        print("\n=== Raw per-sample magnitudes ===")
        print("idx,progress,pos_step,vel,acc,delta_accel")
        progress = last_dump_data["progress"]
        pos_step = last_dump_data["pos_step_mag"]
        vel = last_dump_data["vel_mag"]
        acc = last_dump_data["acc_mag"]
        jerk = last_dump_data["jerk_mag"]
        for i, p in enumerate(progress):
            ps = pos_step[i - 1] if i > 0 else 0.0
            v = vel[i] if i < len(vel) else 0.0
            a = acc[i] if i < len(acc) else 0.0
            j = jerk[i] if i < len(jerk) else 0.0
            print(f"{i},{p:.6f},{ps:.6e},{v:.6e},{a:.6e},{j:.6e}")
        print("\n=== Raw per-sample cameras ===")
        print("idx,progress,level,zoomOffset,tileX,tileY,offsetX,offsetY,globalLevel,globalX,globalY")
        cams = last_dump_data["cameras"]
        for i, (p, cam) in enumerate(zip(progress, cams)):
            print(
                f"{i},{p:.6f},"
                f"{cam['level']},{cam['zoomOffset']:.6f},"
                f"{cam['tileX']},{cam['tileY']},"
                f"{cam['offsetX']:.6f},{cam['offsetY']:.6f},"
                f"{cam['globalLevel']:.6f},{cam['globalX']:.6f},{cam['globalY']:.6f}"
            )

    if any_fail:
        print("\nResult: Non-continuous motion detected.")
        raise SystemExit(1)
    else:
        print("\nResult: No discontinuities found.")


if __name__ == "__main__":
    main()
