#!/usr/bin/env python3
import argparse
import ctypes
import datetime as dt
import json
import math
import os
import sys
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageGrab


DEFAULT_RECT = None
DEFAULT_OFFSETS = "0,0;80,0;-80,0;0,-50;55,-35;-55,-35"
DEFAULT_TEMPLATE_PATH = "vertex_template.json"


@dataclass
class Point:
    x: float
    y: float
    weight: float = 1.0


@dataclass
class FrameData:
    overlay: list[Point]
    stars: list[Point]
    overlay_box: tuple[int, int, int, int]
    magenta_centroid: Point


@dataclass
class DetectionResult:
    frame: FrameData
    stars: list[Point]
    best: tuple
    frame_count: int
    motion_gain: tuple[float, float]


VERTEX_TEMPLATE = None


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()


class DebugLog:
    def __init__(self, root):
        self.enabled = bool(root)
        self.root = None
        self.lines = []
        if self.enabled:
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.root = os.path.join(root, stamp)
            os.makedirs(self.root, exist_ok=True)

    def log(self, text):
        line = f"{time.monotonic():.3f} {text}"
        self.lines.append(line)
        if self.enabled:
            print(f"debug: {text}")

    def save_image(self, name, image):
        if self.enabled:
            image.save(os.path.join(self.root, name))

    def save_text(self):
        if self.enabled:
            with open(os.path.join(self.root, "log.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(self.lines) + "\n")


def is_magenta(r, g, b):
    return r > 105 and b > 115 and g < 135 and r - g > 18 and b - g > 18 and abs(r - b) < 115


def is_star_pixel(r, g, b):
    # White/lavender star pixels. The moving pattern uses similar whites, so callers
    # filter out pixels near the moving overlay when collecting fixed background stars.
    return b > 125 and r > 105 and g > 105 and (r + g + b) > 405 and max(r, g, b) - min(r, g, b) < 105


def brightness(rgb):
    return sum(rgb) / 3


def field_stats(field):
    pix = field.load()
    magenta = []
    star_pixels = 0
    for y in range(field.height):
        for x in range(field.width):
            rgb = pix[x, y]
            if is_magenta(*rgb):
                magenta.append((x, y))
            if is_star_pixel(*rgb):
                star_pixels += 1
    if magenta:
        xs = [p[0] for p in magenta]
        ys = [p[1] for p in magenta]
        box = (min(xs), min(ys), max(xs), max(ys))
    else:
        box = None
    return {"magenta_pixels": len(magenta), "star_pixels": star_pixels, "magenta_box": box}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def is_border_pixel(r, g, b):
    return 85 <= r <= 210 and 85 <= g <= 210 and 90 <= b <= 230 and abs(r - g) < 45 and abs(b - r) < 90


def longest_border_runs(img):
    pix = img.load()
    runs = []
    for y in range(img.height):
        start = None
        prev = None
        row_runs = []
        for x in range(img.width):
            if is_border_pixel(*pix[x, y]):
                if start is None:
                    start = x
                prev = x
            else:
                if start is not None and prev - start + 1 >= 450:
                    row_runs.append((prev - start + 1, start, prev))
                start = None
        if start is not None and prev - start + 1 >= 450:
            row_runs.append((prev - start + 1, start, prev))
        if row_runs:
            length, x0, x1 = max(row_runs)
            runs.append((y, x0, x1, length))
    return runs


def looks_like_star_field_below(screen, x0, x1, y):
    sample_y = y + 40
    if sample_y >= screen.height:
        return False
    pix = screen.load()
    step = max(1, (x1 - x0 + 1) // 80)
    hits = 0
    total = 0
    for x in range(x0 + 20, x1 - 20, step):
        r, g, b = pix[x, sample_y]
        total += 1
        if b >= 45 and b > r + 12 and b > g + 4 and r <= 90 and g <= 100:
            hits += 1
    return total > 0 and hits / total >= 0.55


def auto_detect_rect(screen):
    runs = longest_border_runs(screen)
    best = None
    for i, (top_y, top_x0, top_x1, top_len) in enumerate(runs):
        for bottom_y, bottom_x0, bottom_x1, bottom_len in runs[i + 1:]:
            height = bottom_y - top_y + 1
            if not 250 <= height <= 330:
                continue
            x0 = max(top_x0, bottom_x0)
            x1 = min(top_x1, bottom_x1)
            width = x1 - x0 + 1
            if not 500 <= width <= 650:
                continue
            # Prefer the constellation field dimensions seen in the game UI.
            score = 1000 - abs(width - 553) * 2 - abs(height - 289) * 3
            if best is None or score > best[0]:
                best = (score, x0, top_y, x1, bottom_y)
    if best is None:
        # When the moving constellation starts near the lower edge, it can cover
        # the bottom border. The top border plus the dark blue star field below
        # is still stable enough to infer the usual field height.
        for top_y, top_x0, top_x1, top_len in runs:
            if not 520 <= top_len <= 620:
                continue
            if not int(screen.height * 0.18) <= top_y <= int(screen.height * 0.65):
                continue
            if not looks_like_star_field_below(screen, top_x0, top_x1, top_y):
                continue
            x0, x1 = top_x0, top_x1
            bottom_y = min(screen.height - 1, top_y + 288)
            score = 850 - abs(top_len - 553) * 2 - abs((bottom_y - top_y + 1) - 289) * 3
            if best is None or score > best[0]:
                best = (score, x0, top_y, x1, bottom_y)
    if best is None:
        # Conversely, a large constellation near the top can break the field's
        # upper border while the modal/header top and field bottom remain visible.
        # In that case infer the field top from the usual field height.
        for i, (modal_y, modal_x0, modal_x1, modal_len) in enumerate(runs):
            if not 600 <= modal_len <= 680:
                continue
            if not int(screen.height * 0.18) <= modal_y <= int(screen.height * 0.45):
                continue
            for bottom_y, bottom_x0, bottom_x1, bottom_len in runs[i + 1:]:
                height = bottom_y - modal_y + 1
                if not 340 <= height <= 390:
                    continue
                if not 520 <= bottom_len <= 620:
                    continue
                x0, x1 = bottom_x0, bottom_x1
                top_y = bottom_y - 288
                if top_y <= modal_y + 35:
                    continue
                if not looks_like_star_field_below(screen, x0, x1, top_y):
                    continue
                score = 820 - abs(bottom_len - 553) * 2 - abs(height - 366) * 2
                if best is None or score > best[0]:
                    best = (score, x0, top_y, x1, bottom_y)
    if best is None:
        raise RuntimeError("star field rectangle was not auto-detected")

    _, x0, y0, x1, y1 = best
    margin_x = 22
    rect = (
        max(0, x0 - margin_x),
        max(0, y0),
        min(screen.width, x1 + margin_x + 1) - max(0, x0 - margin_x),
        min(screen.height, y1 + 1) - max(0, y0),
    )
    return rect


def components(points):
    point_set = set(points)
    seen = set()
    result = []
    for start in points:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        comp = []
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    p = (nx, ny)
                    if p in point_set and p not in seen:
                        seen.add(p)
                        stack.append(p)
        result.append(comp)
    return result


def merge_close(points, distance):
    merged = []
    for p in sorted(points, key=lambda q: q.weight, reverse=True):
        for i, cur in enumerate(merged):
            if math.hypot(p.x - cur.x, p.y - cur.y) <= distance:
                w = cur.weight + p.weight
                merged[i] = Point(
                    (cur.x * cur.weight + p.x * p.weight) / w,
                    (cur.y * cur.weight + p.y * p.weight) / w,
                    w,
                )
                break
        else:
            merged.append(p)
    return merged


def median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def field_to_mouse_offset(dx, dy, motion_gain):
    gain_x, gain_y = motion_gain
    if abs(gain_x) < 0.2:
        gain_x = 1.0
    if abs(gain_y) < 0.2:
        gain_y = 1.0
    return dx / gain_x, dy / gain_y


def merge_persistent_stars(star_frames, distance, min_hits):
    clusters = []
    for frame_index, stars in enumerate(star_frames):
        for p in stars:
            for cur in clusters:
                if math.hypot(p.x - cur["x"], p.y - cur["y"]) <= distance:
                    w = cur["weight"] + p.weight
                    cur["x"] = (cur["x"] * cur["weight"] + p.x * p.weight) / w
                    cur["y"] = (cur["y"] * cur["weight"] + p.y * p.weight) / w
                    cur["weight"] = w
                    cur["frames"].add(frame_index)
                    break
            else:
                clusters.append({"x": p.x, "y": p.y, "weight": p.weight, "frames": {frame_index}})

    stars = [
        Point(cur["x"], cur["y"], cur["weight"])
        for cur in clusters
        if len(cur["frames"]) >= min_hits
    ]
    return stars


def bright_centers(img, area):
    pix = img.load()
    x0, y0, x1, y1 = area
    pts = []
    for y in range(max(0, y0), min(img.height - 1, y1) + 1):
        for x in range(max(0, x0), min(img.width - 1, x1) + 1):
            if is_star_pixel(*pix[x, y]):
                pts.append((x, y))

    centers = []
    for comp in components(pts):
        centers.append(
            Point(
                sum(x for x, _ in comp) / len(comp),
                sum(y for _, y in comp) / len(comp),
                len(comp),
            )
        )
    return merge_close(centers, 11.0)


def suppress_close(points, distance):
    chosen = []
    for p in sorted(points, key=lambda q: q.weight, reverse=True):
        if all(math.hypot(p.x - cur.x, p.y - cur.y) > distance for cur in chosen):
            chosen.append(p)
    return chosen


def load_vertex_template(path):
    if not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalized_template_score(pix, template, radius, x, y):
    vals = []
    for yy in range(y - radius, y + radius + 1):
        for xx in range(x - radius, x + radius + 1):
            vals.append(brightness(pix[xx, yy]))
    flat_template = [v for row in template for v in row]
    mean_vals = sum(vals) / len(vals)
    mean_template = sum(flat_template) / len(flat_template)
    std_vals = math.sqrt(sum((v - mean_vals) ** 2 for v in vals)) + 1e-6
    std_template = math.sqrt(sum((v - mean_template) ** 2 for v in flat_template)) + 1e-6
    return sum((vals[i] - mean_vals) * (flat_template[i] - mean_template) for i in range(len(vals))) / (std_vals * std_template)


def detect_overlay_vertices_template(field, box):
    if VERTEX_TEMPLATE is None:
        return None
    radius = int(VERTEX_TEMPLATE["radius"])
    threshold = float(VERTEX_TEMPLATE["threshold"])
    template = np.asarray(VERTEX_TEMPLATE["template"], dtype=np.float32)
    size = radius * 2 + 1

    center_x0 = max(radius, box[0] - 25)
    center_y0 = max(radius, box[1] - 25)
    center_x1 = min(field.width - radius - 1, box[2] + 25)
    center_y1 = min(field.height - radius - 1, box[3] + 25)
    if center_x1 < center_x0 or center_y1 < center_y0:
        return None

    arr = np.asarray(field.convert("L"), dtype=np.float32)
    crop = arr[
        center_y0 - radius : center_y1 + radius + 1,
        center_x0 - radius : center_x1 + radius + 1,
    ]
    windows = np.lib.stride_tricks.sliding_window_view(crop, (size, size))
    flat = windows.reshape(windows.shape[0], windows.shape[1], -1)
    flat = flat - flat.mean(axis=2, keepdims=True)
    denom = np.sqrt((flat * flat).sum(axis=2))

    tmpl = template.reshape(-1)
    tmpl = tmpl - tmpl.mean()
    tmpl_denom = float(np.sqrt((tmpl * tmpl).sum())) + 1e-6
    scores = np.tensordot(flat, tmpl, axes=([2], [0])) / (denom * tmpl_denom + 1e-6)

    ys, xs = np.nonzero(scores >= threshold)
    candidates = [
        Point(float(center_x0 + x), float(center_y0 + y), float(scores[y, x]))
        for y, x in zip(ys, xs)
    ]
    vertices = suppress_close(candidates, 12)
    if len(vertices) < 2:
        return None
    return vertices


def detect_overlay_and_stars(field, allow_clipped=False):
    pix = field.load()
    magenta = []
    for y in range(field.height):
        for x in range(field.width):
            if is_magenta(*pix[x, y]):
                magenta.append((x, y))

    if len(magenta) < 25:
        raise RuntimeError("moving constellation line was not detected")

    mx = [p[0] for p in magenta]
    my = [p[1] for p in magenta]
    box = (min(mx), min(my), max(mx), max(my))
    centroid = Point(sum(mx) / len(mx), sum(my) / len(my), len(magenta))
    box_w = box[2] - box[0] + 1
    box_h = box[3] - box[1] + 1
    touches_edge = box[0] <= 2 or box[1] <= 2 or box[2] >= field.width - 3 or box[3] >= field.height - 3
    # Some valid constellations are tall and can occupy most of the field
    # height. Reject actual edge contact and broad polluted regions, but allow
    # narrow/tall constellations to pass to the template vertex detector.
    too_wide = box_w > field.width * 0.75
    too_broad_and_tall = box_h > field.height * 0.85 and box_w > field.width * 0.45
    if not allow_clipped and (touches_edge or too_wide or too_broad_and_tall):
        raise RuntimeError(f"moving constellation line looks clipped or polluted: box={box}")
    expanded = (box[0] - 20, box[1] - 20, box[2] + 20, box[3] + 20)

    dilated_magenta = set()
    for x, y in magenta:
        for dy in range(-7, 8):
            for dx in range(-7, 8):
                if dx * dx + dy * dy <= 49:
                    dilated_magenta.add((x + dx, y + dy))

    overlay = detect_overlay_vertices_template(field, box)
    if overlay is None:
        overlay = []
        for c in bright_centers(field, expanded):
            near_line = (round(c.x), round(c.y)) in dilated_magenta
            if c.weight >= 15 and near_line:
                overlay.append(c)
        overlay = merge_close(overlay, 13.0)

        if len(overlay) > 8:
            # Long line highlights can be detected as small "stars" on top of the
            # magenta stroke. Real constellation vertices have a larger white cross.
            max_weight = max(c.weight for c in overlay)
            vertex_weight = max(30.0, max_weight * 0.35)
            filtered = [c for c in overlay if c.weight >= vertex_weight]
            if len(filtered) >= 4:
                overlay = filtered

    if len(overlay) < 2:
        raise RuntimeError(f"too few overlay vertices: {len(overlay)}")

    stars = []
    for c in bright_centers(field, (12, 12, field.width - 13, field.height - 13)):
        # Do not discard the whole overlay bounding box. Large constellations can
        # cover much of the field, and that would erase useful background stars.
        # Only remove points that are actually on/near the moving line or vertex glow.
        near_overlay = (round(c.x), round(c.y)) in dilated_magenta or any(
            (c.x - v.x) * (c.x - v.x) + (c.y - v.y) * (c.y - v.y) <= 15.0 * 15.0 for v in overlay
        )
        if c.weight >= 1 and not near_overlay:
            stars.append(c)

    return FrameData(overlay=overlay, stars=stars, overlay_box=box, magenta_centroid=centroid)


def save_detection_debug(debug, label, field, frame):
    if not debug or not debug.enabled:
        return
    marked = field.copy()
    draw = ImageDraw.Draw(marked)
    for p in frame.stars:
        r = 4
        draw.ellipse((p.x - r, p.y - r, p.x + r, p.y + r), outline=(80, 170, 255), width=1)
    for index, p in enumerate(frame.overlay):
        r = 6
        draw.ellipse((p.x - r, p.y - r, p.x + r, p.y + r), outline=(255, 40, 40), width=2)
        draw.text((p.x + 7, p.y - 7), str(index), fill=(255, 80, 80))
    debug.save_image(f"{label}_detected.png", marked)


def save_match_debug(debug, label, field, frame, stars, best):
    if not debug or not debug.enabled:
        return
    _, _, dx, dy, _, _, _ = best
    marked = field.copy()
    draw = ImageDraw.Draw(marked)
    for p in stars:
        r = 3
        draw.ellipse((p.x - r, p.y - r, p.x + r, p.y + r), outline=(70, 160, 255), width=1)
    star_points = [(p.x, p.y) for p in stars]
    for p in frame.overlay:
        r = 4
        draw.ellipse((p.x - r, p.y - r, p.x + r, p.y + r), outline=(255, 40, 40), width=2)
        tx, ty = p.x + dx, p.y + dy
        draw.ellipse((tx - r, ty - r, tx + r, ty + r), outline=(40, 255, 80), width=2)
        if star_points:
            sx, sy = min(star_points, key=lambda s: (s[0] - tx) * (s[0] - tx) + (s[1] - ty) * (s[1] - ty))
            if (sx - tx) * (sx - tx) + (sy - ty) * (sy - ty) <= 11.0 * 11.0:
                draw.line((tx, ty, sx, sy), fill=(255, 255, 0), width=1)
    debug.save_image(f"{label}_match.png", marked)


def find_translation(overlay, stars, tolerance):
    candidates = []
    for op in overlay:
        for sp in stars:
            candidates.append((sp.x - op.x, sp.y - op.y))

    best = None
    for dx, dy in candidates:
        pairs = []
        for overlay_index, op in enumerate(overlay):
            tx = op.x + dx
            ty = op.y + dy
            for star_index, sp in enumerate(stars):
                error = math.hypot(tx - sp.x, ty - sp.y)
                if error <= tolerance:
                    pairs.append((error, overlay_index, star_index))

        used_overlay = set()
        used_stars = set()
        matched_errors = []
        for error, overlay_index, star_index in sorted(pairs):
            if overlay_index in used_overlay or star_index in used_stars:
                continue
            used_overlay.add(overlay_index)
            used_stars.add(star_index)
            matched_errors.append(error)
        matched = len(matched_errors)
        if matched == 0:
            continue
        avg_error = sum(matched_errors) / matched
        coverage = matched / len(overlay)
        score = matched * 100.0 + coverage * 20.0 - avg_error * 4.0
        if best is None or score > best[0]:
            best = (score, matched, dx, dy, avg_error, max(matched_errors), coverage)

    if best is None:
        raise RuntimeError("no matching translation candidate was found")
    return best


class Mouse:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    @staticmethod
    def pos():
        pt = Mouse.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    @staticmethod
    def move_to(x, y):
        ctypes.windll.user32.SetCursorPos(int(round(x)), int(round(y)))

    @staticmethod
    def click():
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.03)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


def grab_screen():
    return ImageGrab.grab(all_screens=True).convert("RGB")


def resolve_rect(screen, rect):
    return auto_detect_rect(screen) if rect is None else rect


def grab_field(rect, debug=None, label=None, save_full=False, screen=None):
    if screen is None:
        screen = grab_screen()
    rect = resolve_rect(screen, rect)
    rx, ry, rw, rh = rect
    field = screen.crop((rx, ry, rx + rw, ry + rh))
    if debug and debug.enabled and label:
        debug.save_image(f"{label}_field.png", field)
        if save_full:
            marked = screen.copy()
            draw = ImageDraw.Draw(marked)
            draw.rectangle((rx, ry, rx + rw, ry + rh), outline=(255, 0, 0), width=3)
            debug.save_image(f"{label}_full.png", marked)
        debug.log(f"{label}: mouse={Mouse.pos()} rect={rect} stats={field_stats(field)}")
    return field


def load_image_field(path, rect):
    img = Image.open(path).convert("RGB")
    rect = resolve_rect(img, rect)
    rx, ry, rw, rh = rect
    return img.crop((rx, ry, rx + rw, ry + rh))


def parse_rect(text):
    if text.lower() == "auto":
        return None
    values = [int(v.strip()) for v in text.split(",")]
    if len(values) != 4:
        raise argparse.ArgumentTypeError("rect must be x,y,width,height")
    return tuple(values)


def parse_offsets(text):
    offsets = []
    if not text.strip():
        return offsets
    for item in text.split(";"):
        x, y = item.split(",")
        offsets.append((int(x), int(y)))
    return offsets


def required_match_count(overlay_count, min_matches, min_coverage):
    if overlay_count <= 4:
        return overlay_count
    if overlay_count <= 9:
        return overlay_count - 1
    return overlay_count - 2


def confidence_ok(best, overlay_count, min_matches, min_coverage):
    _, matched, _, _, avg_error, max_error, coverage = best
    required = required_match_count(overlay_count, min_matches, min_coverage)
    return matched >= required and avg_error <= 3.0 and max_error <= 6.0


def analyze_static_image(args):
    field = load_image_field(args.image, args.rect)
    frame = detect_overlay_and_stars(field)
    best = find_translation(frame.overlay, frame.stars, args.tolerance)
    print_result("static", frame, frame.stars, best)
    return best, frame


def sample_live(args, debug=None, attempt=0):
    rect = args.rect
    rx, ry, rw, rh = rect
    if debug and debug.enabled:
        debug.log(f"attempt{attempt:02d}: resolved_rect={rect}")
    if args.base == "center":
        start_x, start_y = rx + rw / 2, ry + rh / 2
    else:
        start_x, start_y = Mouse.pos()
    offsets = args.offsets
    frames = []
    all_stars = []
    star_frames = []
    motion_samples_x = []
    motion_samples_y = []
    clipped_sweep_frames = 0

    def try_precenter(prefix, save_first_full):
        nonlocal start_x, start_y
        for round_index in range(3):
            label = f"{prefix}" if round_index == 0 else f"{prefix}_precentered{round_index}"
            field_for_center = grab_field(rect, debug, label, save_full=(save_first_full and round_index == 0))
            try:
                frame_for_center = detect_overlay_and_stars(field_for_center, allow_clipped=True)
                bx0, by0, bx1, by1 = frame_for_center.overlay_box
                source = "vertices"
            except Exception:
                stats = field_stats(field_for_center)
                if stats["magenta_pixels"] < 5 or stats["magenta_box"] is None:
                    raise
                bx0, by0, bx1, by1 = stats["magenta_box"]
                source = "magenta"
            box_cx = (bx0 + bx1) / 2
            box_cy = (by0 + by1) / 2
            target_x = rw / 2
            target_y = rh / 2
            adjust_x = clamp(target_x - box_cx, -220.0, 220.0)
            adjust_y = clamp(target_y - box_cy, -130.0, 130.0)
            if debug and debug.enabled:
                debug.log(
                    f"attempt{attempt:02d}: precenter round={round_index} source={source} "
                    f"box=({bx0},{by0},{bx1},{by1}) adjust=({adjust_x:.1f},{adjust_y:.1f})"
                )
            if abs(adjust_x) <= 4 and abs(adjust_y) <= 4:
                break
            start_x += adjust_x
            start_y += adjust_y
            Mouse.move_to(start_x, start_y)
            time.sleep(args.settle)
        return True

    Mouse.move_to(start_x, start_y)
    time.sleep(args.settle)

    try:
        try_precenter(f"attempt{attempt:02d}_initial", True)
    except Exception as exc:
        if debug and debug.enabled:
            debug.log(f"attempt{attempt:02d}: precenter initial skipped: {exc}")
        recovered = False
        home_x, home_y = (rx + rw / 2, ry + rh / 2) if args.base == "center" else Mouse.pos()
        recovery_offsets = [(-180, -110), (-220, -140), (-120, -150), (0, -140), (180, -110), (-220, 0), (220, 0), (0, 120)]
        for recovery_index, (rdx, rdy) in enumerate(recovery_offsets):
            start_x, start_y = home_x + rdx, home_y + rdy
            Mouse.move_to(start_x, start_y)
            time.sleep(args.settle)
            try:
                try_precenter(f"attempt{attempt:02d}_recover{recovery_index:02d}", False)
                recovered = True
                break
            except Exception as recover_exc:
                if debug and debug.enabled:
                    debug.log(f"attempt{attempt:02d}: recover{recovery_index:02d} skipped: {recover_exc}")
                start_x, start_y = home_x, home_y
                Mouse.move_to(start_x, start_y)
        if not recovered and debug and debug.enabled:
            debug.log(f"attempt{attempt:02d}: precenter skipped")
        if not recovered:
            start_x, start_y = home_x, home_y
            Mouse.move_to(start_x, start_y)

    base_frame = None
    base_centroid = None
    for index, (dx, dy) in enumerate(offsets):
        Mouse.move_to(start_x + dx, start_y + dy)
        time.sleep(args.settle)
        label = f"attempt{attempt:02d}_sweep{index:02d}_{int(dx)}_{int(dy)}"
        field = grab_field(rect, debug, label)
        try:
            frame = detect_overlay_and_stars(field)
        except Exception as exc:
            if "clipped or polluted" in str(exc):
                clipped_sweep_frames += 1
            if debug and debug.enabled:
                debug.log(f"{label}: skipped={exc}")
            continue
        save_detection_debug(debug, label, field, frame)
        if debug and debug.enabled:
            debug.log(f"{label}: overlay={len(frame.overlay)} stars={len(frame.stars)} box={frame.overlay_box}")
        if dx == 0 and dy == 0 and base_frame is None:
            base_frame = frame
            base_centroid = frame.magenta_centroid
        elif base_centroid is not None:
            if dx != 0:
                motion_samples_x.append((frame.magenta_centroid.x - base_centroid.x) / dx)
            if dy != 0:
                motion_samples_y.append((frame.magenta_centroid.y - base_centroid.y) / dy)
        frames.append(frame)
        all_stars.extend(frame.stars)
        star_frames.append(frame.stars)

    Mouse.move_to(start_x, start_y)
    time.sleep(args.settle)
    label = f"attempt{attempt:02d}_current"
    field = grab_field(rect, debug, label)
    try:
        current = detect_overlay_and_stars(field)
        save_detection_debug(debug, label, field, current)
        if debug and debug.enabled:
            debug.log(f"{label}: overlay={len(current.overlay)} stars={len(current.stars)} box={current.overlay_box}")
        frames.append(current)
        all_stars.extend(current.stars)
        star_frames.append(current.stars)
    except Exception as exc:
        if base_frame is None:
            raise
        if "moving constellation line was not detected" in str(exc):
            raise RuntimeError(f"current frame lost moving constellation: {exc}")
        current = base_frame
        if debug and debug.enabled:
            debug.log(f"{label}: using base frame because current failed: {exc}")

    # Fixed background stars appear at stable field coordinates across frames.
    # Moving overlay artifacts are excluded per frame and then merged here.
    if len(frames) < 2:
        raise RuntimeError(f"too few usable sweep frames: {len(frames)}")
    min_hits = min(args.min_star_frames, len(star_frames))
    # When large constellations sit near an edge, several sweep frames can be
    # clipped and skipped. Keep the click confidence strict, but avoid starving
    # the matcher of background candidates in that sparse-frame case.
    if clipped_sweep_frames > 0 and len(star_frames) <= 4 and min_hits > 2:
        min_hits = 2
        if debug and debug.enabled:
            debug.log(
                f"attempt{attempt:02d}: sparse_usable_frames={len(star_frames)} "
                f"clipped_sweep_frames={clipped_sweep_frames} "
                f"persistent_star_frames lowered to {min_hits}"
            )
    stars = merge_persistent_stars(star_frames, args.merge_distance, min_hits)
    if len(stars) < args.min_background_stars and min_hits > 1:
        min_hits -= 1
        stars = merge_persistent_stars(star_frames, args.merge_distance, min_hits)
    if debug and debug.enabled:
        debug.log(f"attempt{attempt:02d}: persistent_star_frames={min_hits} persistent_stars={len(stars)} raw_stars={len(all_stars)}")
    best = find_translation(current.overlay, stars, args.tolerance)
    valid_gain_x = [g for g in motion_samples_x if 0.5 <= abs(g) <= 2.0]
    valid_gain_y = [g for g in motion_samples_y if 0.5 <= abs(g) <= 2.0]
    gain_x = median(valid_gain_x) if valid_gain_x else 1.0
    gain_y = median(valid_gain_y) if valid_gain_y else 1.0
    if not valid_gain_y and valid_gain_x:
        gain_y = gain_x
    if not valid_gain_x and valid_gain_y:
        gain_x = gain_y
    if debug and debug.enabled:
        debug.log(f"attempt{attempt:02d}: motion_gain=({gain_x:.3f},{gain_y:.3f}) samples_x={motion_samples_x} samples_y={motion_samples_y}")
        debug.log(f"attempt{attempt:02d}: merged_stars={len(stars)} best={best}")
        save_match_debug(debug, f"attempt{attempt:02d}_current", field, current, stars, best)
    return DetectionResult(current, stars, best, len(frames), (gain_x, gain_y))


def print_result(mode, frame, stars, best, frames=1):
    score, matched, dx, dy, avg_error, max_error, coverage = best
    print(
        f"mode={mode} frames={frames} overlay_vertices={len(frame.overlay)} "
        f"background_stars={len(stars)} matched={matched}/{len(frame.overlay)} "
        f"coverage={coverage:.2f}"
    )
    print(
        f"field_offset=({dx:.1f},{dy:.1f}) score={score:.1f} "
        f"avg_error={avg_error:.1f} max_matched_error={max_error:.1f} "
        f"overlay_box={frame.overlay_box}"
    )


def move_to_target_with_verify(args, debug, stars, motion_gain, nx, ny, label):
    Mouse.move_to(nx, ny)
    time.sleep(max(args.settle * 2, 0.10))
    field = grab_field(args.rect, debug, f"{label}_after_move")
    try:
        frame = detect_overlay_and_stars(field, allow_clipped=True)
        residual = find_translation(frame.overlay, stars, args.tolerance)
        save_detection_debug(debug, f"{label}_after_move", field, frame)
        save_match_debug(debug, f"{label}_after_move", field, frame, stars, residual)
        required = required_match_count(len(frame.overlay), args.min_matches, args.min_coverage)
        if debug.enabled:
            debug.log(
                f"{label}: after_move matched={residual[1]}/{len(frame.overlay)} "
                f"required={required} offset=({residual[2]:.1f},{residual[3]:.1f}) "
                f"avg_error={residual[4]:.1f} max_error={residual[5]:.1f}"
            )
        if confidence_ok(residual, len(frame.overlay), args.min_matches, args.min_coverage):
            rdx, rdy = residual[2], residual[3]
            if abs(rdx) > 2.0 or abs(rdy) > 2.0:
                mdx, mdy = field_to_mouse_offset(rdx, rdy, motion_gain)
                cx, cy = Mouse.pos()
                nx, ny = cx + mdx, cy + mdy
                if debug.enabled:
                    debug.log(f"{label}: final_adjust mouse_offset=({mdx:.1f},{mdy:.1f}) target=({nx:.0f},{ny:.0f})")
                Mouse.move_to(nx, ny)
                time.sleep(max(args.settle * 2, 0.10))
            return True
    except Exception as exc:
        if debug.enabled:
            debug.log(f"{label}: after_move verify failed: {exc}")
    return False


def is_start_dialog_gray(r, g, b):
    return 75 <= r <= 180 and 75 <= g <= 180 and 75 <= b <= 180 and max(r, g, b) - min(r, g, b) <= 45


def is_start_panel_dark(r, g, b):
    return 35 <= r <= 115 and 35 <= g <= 115 and 35 <= b <= 115 and max(r, g, b) - min(r, g, b) <= 35


def find_auto_fish_button(screen):
    # The fishing prompt is a dark gray modal around the lower center of the
    # screen. The "自分で釣る" button is the small gray rectangle near its bottom.
    pix = screen.load()
    x0 = int(screen.width * 0.32)
    x1 = int(screen.width * 0.68)
    y0 = int(screen.height * 0.34)
    y1 = int(screen.height * 0.74)
    panel_mask = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if is_start_panel_dark(*pix[x, y]):
                panel_mask.append((x, y))

    panels = []
    for comp in components(panel_mask):
        if len(comp) < 8000:
            continue
        xs = [p[0] for p in comp]
        ys = [p[1] for p in comp]
        px0, py0, px1, py1 = min(xs), min(ys), max(xs), max(ys)
        pw = px1 - px0 + 1
        ph = py1 - py0 + 1
        if 180 <= pw <= 330 and 130 <= ph <= 260:
            panels.append((len(comp), (px0, py0, px1, py1)))
    if not panels:
        boxes = find_auto_fish_button_fallback(screen, x0, x1, y0, y1)
        if not boxes:
            return None
        _, box = max(boxes, key=lambda item: item[0])
        bx0, by0, bx1, by1 = box
        return ((bx0 + bx1) / 2, (by0 + by1) / 2, box)

    boxes = []
    for panel_area, panel in panels:
        px0, py0, px1, py1 = panel
        pw = px1 - px0 + 1
        ph = py1 - py0 + 1
        mask = []
        for y in range(py0, py1 + 1):
            for x in range(px0, px1 + 1):
                if is_start_dialog_gray(*pix[x, y]):
                    mask.append((x, y))

        for comp in components(mask):
            if len(comp) < 500:
                continue
            xs = [p[0] for p in comp]
            ys = [p[1] for p in comp]
            bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
            w = bx1 - bx0 + 1
            h = by1 - by0 + 1
            bcx = (bx0 + bx1) / 2
            if 45 <= w <= 120 and 28 <= h <= 48 and screen.width * 0.43 <= bcx <= screen.width * 0.62 and by0 >= py0 + ph * 0.65:
                # Prefer the button-sized component near the bottom of an
                # actual fishing prompt panel. Checking every candidate panel
                # handles reward popups overlapping the prompt.
                score = (
                    panel_area / 100.0
                    + by0 - py0
                    - abs(w - 58) * 2.0
                    - abs(h - 35) * 2.0
                    - abs((bcx - px0) / pw - 0.50) * 80.0
                )
                boxes.append((score, (bx0, by0, bx1, by1)))

    if not boxes:
        boxes = find_auto_fish_button_fallback(screen, x0, x1, y0, y1)
        if not boxes:
            return None
    _, box = max(boxes, key=lambda item: item[0])
    bx0, by0, bx1, by1 = box
    return ((bx0 + bx1) / 2, (by0 + by1) / 2, box)


def find_auto_fish_button_fallback(screen, x0, x1, y0, y1):
    # Reward popups can overlap the fishing prompt after a successful round.
    # In that state the prompt panel is no longer the largest dark component,
    # but the small "自分で釣る" button remains visible near the lower center.
    pix = screen.load()
    mask = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if is_start_dialog_gray(*pix[x, y]):
                mask.append((x, y))

    gray_components = []
    boxes = []
    for comp in components(mask):
        if len(comp) < 450:
            continue
        xs = [p[0] for p in comp]
        ys = [p[1] for p in comp]
        bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
        w = bx1 - bx0 + 1
        h = by1 - by0 + 1
        bcx = (bx0 + bx1) / 2
        bcy = (by0 + by1) / 2
        gray_components.append((len(comp), bx0, by0, bx1, by1, w, h, bcx, bcy))

    for _, bx0, by0, bx1, by1, w, h, bcx, bcy in gray_components:
        if not (45 <= w <= 120 and 28 <= h <= 48):
            continue
        if not (screen.width * 0.43 <= bcx <= screen.width * 0.58):
            continue
        if not (screen.height * 0.50 <= bcy <= screen.height * 0.68):
            continue

        text_bands = 0
        for _, tx0, ty0, tx1, ty1, tw, th, tcx, _ in gray_components:
            if tw < 170 or th < 25 or th > 90:
                continue
            if not (bcy - 230 <= ty0 and ty1 <= by0 - 45):
                continue
            overlap = min(bx1 + 170, tx1) - max(bx0 - 170, tx0) + 1
            if overlap > 0 and abs(tcx - bcx) <= 170:
                text_bands += 1
        if text_bands < 1:
            continue

        dark_hits = 0
        total = 0
        for sy in range(max(0, by0 - 95), max(0, by0 - 15), 4):
            for sx in range(max(0, bx0 - 90), min(screen.width, bx1 + 91), 4):
                total += 1
                if is_start_panel_dark(*pix[sx, sy]):
                    dark_hits += 1
        if total == 0 or dark_hits / total < 0.25:
            continue
        score = 500 - abs(w - 58) * 2.0 - abs(h - 35) * 2.0 - abs(bcx - screen.width * 0.47) / 4.0
        boxes.append((score, (bx0, by0, bx1, by1)))
    return boxes


def wait_and_click_auto_fish(args, debug, loop_index):
    deadline = time.monotonic() + args.start_wait_timeout
    last_seen = None
    stable_found = None
    stable_count = 0
    while time.monotonic() < deadline:
        screen = grab_screen()
        found = find_auto_fish_button(screen)
        if found:
            x, y, box = found
            if stable_found:
                last_x, last_y, _ = stable_found
                if math.hypot(x - last_x, y - last_y) <= args.start_confirm_distance:
                    stable_count += 1
                else:
                    stable_count = 1
            else:
                stable_count = 1
            stable_found = found
            if stable_count < args.start_confirm_frames:
                if debug.enabled:
                    debug.log(
                        f"loop{loop_index:03d}: start_button candidate "
                        f"box={box} click=({x:.0f},{y:.0f}) stable={stable_count}/{args.start_confirm_frames}"
                    )
                time.sleep(args.start_poll_interval)
                continue
            if debug.enabled:
                marked = screen.copy()
                draw = ImageDraw.Draw(marked)
                draw.rectangle(box, outline=(255, 0, 0), width=3)
                debug.save_image(f"loop{loop_index:03d}_start_button.png", marked)
                debug.log(
                    f"loop{loop_index:03d}: start_button box={box} click=({x:.0f},{y:.0f}) "
                    f"stable={stable_count}/{args.start_confirm_frames}"
                )
            if not args.dry_run:
                Mouse.move_to(x, y)
                time.sleep(0.08)
                actual_x, actual_y = Mouse.pos()
                if debug.enabled:
                    marked = screen.copy()
                    draw = ImageDraw.Draw(marked)
                    draw.rectangle(box, outline=(255, 0, 0), width=3)
                    draw.line((actual_x - 12, actual_y, actual_x + 12, actual_y), fill=(0, 255, 0), width=2)
                    draw.line((actual_x, actual_y - 12, actual_x, actual_y + 12), fill=(0, 255, 0), width=2)
                    debug.save_image(f"loop{loop_index:03d}_start_click_pos.png", marked)
                    debug.log(
                        f"loop{loop_index:03d}: start_click target=({x:.0f},{y:.0f}) "
                        f"actual=({actual_x},{actual_y}) delta=({actual_x - x:.1f},{actual_y - y:.1f})"
                    )
                    debug.save_text()
                Mouse.click()
            else:
                print(f"DRY-RUN start: would click auto-fish button at ({x:.0f},{y:.0f})")
            return True
        stable_found = None
        stable_count = 0
        if last_seen is None or time.monotonic() - last_seen > 2.0:
            last_seen = time.monotonic()
            if debug.enabled:
                debug.log(f"loop{loop_index:03d}: waiting for start button")
        time.sleep(args.start_poll_interval)
    raise RuntimeError("start button was not detected before timeout")


def move_to_expected_star_field_center(args, debug, loop_index):
    screen = grab_screen()
    if args.rect is not None:
        rx, ry, rw, rh = args.rect
        x, y = rx + rw / 2, ry + rh / 2
    else:
        x, y = screen.width / 2, screen.height * 0.47
    Mouse.move_to(x, y)
    if debug.enabled:
        debug.log(f"loop{loop_index:03d}: moved_to_expected_field_center target=({x:.0f},{y:.0f}) actual={Mouse.pos()}")


def wait_for_star_field(args, debug, loop_index):
    deadline = time.monotonic() + args.field_wait_timeout
    last_seen = None
    last_error = None
    while time.monotonic() < deadline:
        screen = grab_screen()
        try:
            rect = auto_detect_rect(screen)
            if debug.enabled:
                marked = screen.copy()
                draw = ImageDraw.Draw(marked)
                rx, ry, rw, rh = rect
                draw.rectangle((rx, ry, rx + rw, ry + rh), outline=(255, 0, 0), width=3)
                debug.save_image(f"loop{loop_index:03d}_star_field_ready.png", marked)
                debug.log(f"loop{loop_index:03d}: star_field_ready rect={rect}")
                debug.save_text()
            return rect
        except Exception as exc:
            last_error = str(exc)
            if last_seen is None or time.monotonic() - last_seen > 0.75:
                last_seen = time.monotonic()
                if debug.enabled:
                    debug.log(f"loop{loop_index:03d}: waiting for star field: {last_error}")
        time.sleep(args.field_poll_interval)

    if debug.enabled:
        debug.save_image(f"loop{loop_index:03d}_star_field_timeout.png", grab_screen())
        debug.log(f"loop{loop_index:03d}: star_field_timeout last_error={last_error}")
        debug.save_text()
    raise RuntimeError(f"star field did not appear after start click: {last_error}")


def run_constellation_once(args, debug):
    args.rect = resolve_rect(grab_screen(), args.rect)
    if debug.enabled:
        debug.log(f"locked_rect={args.rect}")

    deadline = time.monotonic() + args.retry_until
    last_error = None
    attempt = 0
    while True:
        try:
            result = sample_live(args, debug, attempt)
            frame, stars, best, frame_count = result.frame, result.stars, result.best, result.frame_count
            print_result("live-sweep", frame, stars, best, frame_count)
            if confidence_ok(best, len(frame.overlay), args.min_matches, args.min_coverage):
                _, _, dx, dy, _, _, _ = best
                cx, cy = Mouse.pos()
                mdx, mdy = field_to_mouse_offset(dx, dy, result.motion_gain)
                nx, ny = cx + mdx, cy + mdy
                print(f"mouse=({cx},{cy}) -> ({nx:.0f},{ny:.0f}) field_offset=({dx:.1f},{dy:.1f}) gain=({result.motion_gain[0]:.3f},{result.motion_gain[1]:.3f})")
                if debug.enabled:
                    debug.log(
                        f"click matched={best[1]}/{len(frame.overlay)} "
                        f"required={required_match_count(len(frame.overlay), args.min_matches, args.min_coverage)} "
                        f"coverage={best[6]:.2f} avg_error={best[4]:.1f} "
                        f"mouse=({cx},{cy}) field_offset=({dx:.1f},{dy:.1f}) "
                        f"motion_gain=({result.motion_gain[0]:.3f},{result.motion_gain[1]:.3f}) "
                        f"mouse_offset=({mdx:.1f},{mdy:.1f}) target=({nx:.0f},{ny:.0f})"
                    )
                    debug.save_text()
                if args.dry_run:
                    print(f"DRY-RUN success: would move to ({nx:.0f},{ny:.0f}) and click")
                    return 0
                if not move_to_target_with_verify(args, debug, stars, result.motion_gain, nx, ny, f"attempt{attempt:02d}_final"):
                    last_error = "final move verification failed"
                    if debug.enabled:
                        debug.log(f"attempt{attempt:02d}: {last_error}")
                    continue
                debug.save_text()
                if not args.move_only:
                    Mouse.click()
                return 0
            last_error = "low confidence"
            if debug.enabled:
                debug.log(f"attempt{attempt:02d}: low confidence")
        except Exception as exc:
            last_error = str(exc)
            if debug.enabled:
                debug.log(f"attempt{attempt:02d}: error={last_error}")

        if time.monotonic() >= deadline:
            debug.save_text()
            raise RuntimeError(f"gave up before confident click: {last_error}")
        time.sleep(args.retry_interval)
        attempt += 1


def main():
    global VERTEX_TEMPLATE
    parser = argparse.ArgumentParser(description="Find and click the matching constellation position.")
    parser.add_argument("--image", help="Analyze a screenshot PNG instead of the live screen.")
    parser.add_argument("--rect", type=parse_rect, default=DEFAULT_RECT, help="Star field rectangle: x,y,width,height or auto")
    parser.add_argument("--tolerance", type=float, default=11.0, help="Pixel tolerance for star matching")
    parser.add_argument("--merge-distance", type=float, default=8.0, help="Merge distance for background stars sampled across frames")
    parser.add_argument("--min-star-frames", type=int, default=3, help="Keep background stars seen in at least this many sweep frames")
    parser.add_argument("--min-background-stars", type=int, default=25, help="Fallback to a lower min-star-frames if fewer stars remain")
    parser.add_argument("--offsets", type=parse_offsets, default=parse_offsets(DEFAULT_OFFSETS), help="Cursor sweep offsets: x,y;x,y")
    parser.add_argument("--base", choices=("center", "current"), default="center", help="Sweep base. center uses the star field center; current uses current cursor position")
    parser.add_argument("--start-delay", type=float, default=2.5, help="Seconds to wait before live capture starts, so you can return focus to the game")
    parser.add_argument("--settle", type=float, default=0.045, help="Seconds to wait after each cursor move")
    parser.add_argument("--retry-until", type=float, default=8.0, help="Retry seconds before giving up. Late retries benefit from disappearing decoy stars.")
    parser.add_argument("--retry-interval", type=float, default=0.35, help="Seconds between retries")
    parser.add_argument("--min-matches", type=int, default=3, help="Minimum matched overlay vertices before clicking")
    parser.add_argument("--min-coverage", type=float, default=0.50, help="Minimum matched overlay ratio before clicking")
    parser.add_argument("--dry-run", action="store_true", help="Print detection result without moving/clicking to the final position")
    parser.add_argument("--move-only", action="store_true", help="Move mouse to the detected position without clicking")
    parser.add_argument("--debug-dir", help="Save captured fields and log files under this directory")
    parser.add_argument("--vertex-template", default=DEFAULT_TEMPLATE_PATH, help="Learned vertex template JSON")
    parser.add_argument("--auto-loop", action="store_true", help="Wait for the fishing prompt, click the start button, clear the constellation, and repeat")
    parser.add_argument("--loop-count", type=int, default=0, help="Number of auto-loop cycles. 0 means run until stopped")
    parser.add_argument("--start-wait-timeout", type=float, default=90.0, help="Seconds to wait for the fishing start prompt in auto-loop mode")
    parser.add_argument("--start-poll-interval", type=float, default=0.25, help="Seconds between start prompt checks")
    parser.add_argument("--start-confirm-frames", type=int, default=2, help="Require this many consecutive start button detections before clicking")
    parser.add_argument("--start-confirm-distance", type=float, default=6.0, help="Maximum pixel drift allowed between consecutive start button detections")
    parser.add_argument("--after-start-delay", type=float, default=0.2, help="Seconds to wait after clicking the fishing start button before solving the constellation")
    parser.add_argument("--field-wait-timeout", type=float, default=5.0, help="Seconds to wait for the constellation field after clicking the fishing start button")
    parser.add_argument("--field-poll-interval", type=float, default=0.10, help="Seconds between constellation field checks after the start click")
    args = parser.parse_args()
    debug = DebugLog(args.debug_dir)
    VERTEX_TEMPLATE = load_vertex_template(args.vertex_template)
    if debug.enabled and VERTEX_TEMPLATE:
        debug.log(f"vertex_template={args.vertex_template} threshold={VERTEX_TEMPLATE.get('threshold')} radius={VERTEX_TEMPLATE.get('radius')}")

    if args.image:
        best, frame = analyze_static_image(args)
        if not confidence_ok(best, len(frame.overlay), args.min_matches, args.min_coverage):
            raise RuntimeError("static image confidence is low")
        return 0

    if args.auto_loop:
        print("Auto-loop mode. Focus the game window now; press Ctrl+C in this console to stop.")
        if args.start_delay > 0:
            time.sleep(args.start_delay)
        loop_index = 0
        while args.loop_count <= 0 or loop_index < args.loop_count:
            if debug.enabled:
                debug.log(f"loop{loop_index:03d}: begin")
            try:
                wait_and_click_auto_fish(args, debug, loop_index)
                move_to_expected_star_field_center(args, debug, loop_index)
                time.sleep(args.after_start_delay)
                args.rect = wait_for_star_field(args, debug, loop_index)
                run_constellation_once(args, debug)
                if debug.enabled:
                    debug.log(f"loop{loop_index:03d}: complete")
                    debug.save_text()
            except Exception as exc:
                if debug.enabled:
                    debug.log(f"loop{loop_index:03d}: skipped_after_error={exc}")
                    debug.save_text()
                print(f"loop{loop_index:03d}: skipped after error: {exc}")
            loop_index += 1
            time.sleep(0.5)
        return 0

    if args.start_delay > 0:
        print(f"Starting in {args.start_delay:.1f}s. Focus the game window now.")
        time.sleep(args.start_delay)

    return run_constellation_once(args, debug)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
