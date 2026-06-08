#!/usr/bin/env python3
import argparse
import math
import os
from dataclasses import dataclass

from PIL import Image, ImageDraw


@dataclass
class Point:
    x: float
    y: float
    score: float = 1.0


def is_magenta(r, g, b):
    return r > 105 and b > 115 and g < 135 and r - g > 18 and b - g > 18 and abs(r - b) < 115


def brightness(rgb):
    return sum(rgb) / 3


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


def merge(points, distance):
    out = []
    for p in sorted(points, key=lambda q: q.score, reverse=True):
        for i, cur in enumerate(out):
            if math.hypot(p.x - cur.x, p.y - cur.y) <= distance:
                w = cur.score + p.score
                out[i] = Point((cur.x * cur.score + p.x * p.score) / w, (cur.y * cur.score + p.y * p.score) / w, w)
                break
        else:
            out.append(p)
    return out


def suppress_close(points, distance):
    chosen = []
    for p in sorted(points, key=lambda q: q.score, reverse=True):
        if all(math.hypot(p.x - cur.x, p.y - cur.y) > distance for cur in chosen):
            chosen.append(p)
    return chosen


def magenta_box(img):
    pix = img.load()
    pts = []
    for y in range(img.height):
        for x in range(img.width):
            if is_magenta(*pix[x, y]):
                pts.append((x, y))
    if not pts:
        raise RuntimeError("no magenta line")
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    return (min(xs), min(ys), max(xs), max(ys)), pts


def line_endpoint_candidates(img):
    _, magenta = magenta_box(img)
    out = []
    for comp in components(magenta):
        if len(comp) < 4:
            continue
        cx = sum(x for x, _ in comp) / len(comp)
        cy = sum(y for _, y in comp) / len(comp)
        a = max(comp, key=lambda q: (q[0] - cx) ** 2 + (q[1] - cy) ** 2)
        b = max(comp, key=lambda q: (q[0] - a[0]) ** 2 + (q[1] - a[1]) ** 2)
        score = min(30.0, len(comp))
        out.append(Point(a[0], a[1], score))
        out.append(Point(b[0], b[1], score))
    return merge(out, 6)


def cross_score_candidates(img):
    pix = img.load()
    box, magenta = magenta_box(img)
    mag_set = set(magenta)
    out = []

    def br(x, y):
        if x < 0 or y < 0 or x >= img.width or y >= img.height:
            return 0
        return brightness(pix[x, y])

    for y in range(max(8, box[1] - 22), min(img.height - 8, box[3] + 23)):
        for x in range(max(8, box[0] - 22), min(img.width - 8, box[2] + 23)):
            center = sum(br(x + dx, y + dy) for dx in range(-2, 3) for dy in range(-2, 3)) / 25
            east = max(br(x + r, y) for r in range(5, 12))
            west = max(br(x - r, y) for r in range(5, 12))
            south = max(br(x, y + r) for r in range(5, 12))
            north = max(br(x, y - r) for r in range(5, 12))
            arms = [east, west, south, north]
            arm_avg = sum(arms) / 4
            symmetry = abs(east - west) + abs(north - south)
            mag_near = 0
            for yy in range(y - 12, y + 13):
                for xx in range(x - 12, x + 13):
                    if (xx - x) ** 2 + (yy - y) ** 2 <= 144 and (xx, yy) in mag_set:
                        mag_near += 1
            score = (arm_avg - center) * 2.0 + min(mag_near, 18) * 3.0 - symmetry * 0.25
            if center < 125 and arm_avg > 145 and min(arms) > 95 and mag_near >= 2 and score > 165:
                out.append(Point(x, y, score))
    return suppress_close(out, 7)


def detect_vertices(img):
    endpoints = line_endpoint_candidates(img)
    crosses = cross_score_candidates(img)
    combined = []
    for p in endpoints:
        combined.append(Point(p.x, p.y, p.score * 2.0))
    for p in crosses:
        # Cross candidates are useful for centering, but bright background stars
        # can look similar. Prefer those near magenta endpoints.
        nearest_endpoint = min((math.hypot(p.x - e.x, p.y - e.y) for e in endpoints), default=999)
        if nearest_endpoint <= 12:
            combined.append(Point(p.x, p.y, p.score + max(0, 12 - nearest_endpoint) * 30))
    return suppress_close(combined, 7)


def draw_vertices(img, vertices, out_path):
    marked = img.copy()
    draw = ImageDraw.Draw(marked)
    for i, p in enumerate(sorted(vertices, key=lambda q: (q.y, q.x))):
        r = 5
        draw.ellipse((p.x - r, p.y - r, p.x + r, p.y + r), outline=(255, 0, 0), width=2)
        draw.text((p.x + 6, p.y - 6), str(i), fill=(255, 0, 0))
    marked.save(out_path)


def extract_red_annotations(path):
    img = Image.open(path).convert("RGB")
    pix = img.load()
    pts = []
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = pix[x, y]
            if r > 180 and g < 100 and b < 100:
                pts.append((x, y))
    out = []
    for comp in components(pts):
        if len(comp) >= 5:
            out.append(Point(sum(x for x, _ in comp) / len(comp), sum(y for _, y in comp) / len(comp), len(comp)))
    return out


def build_template(training_pairs, radius):
    patches = []
    size = radius * 2 + 1
    for image_path, annotation_path in training_pairs:
        img = Image.open(image_path).convert("RGB")
        pix = img.load()
        for pt in extract_red_annotations(annotation_path):
            cx = int(round(pt.x))
            cy = int(round(pt.y))
            if cx < radius or cy < radius or cx >= img.width - radius or cy >= img.height - radius:
                continue
            patch = []
            for y in range(cy - radius, cy + radius + 1):
                row = []
                for x in range(cx - radius, cx + radius + 1):
                    row.append(brightness(pix[x, y]))
                patch.append(row)
            patches.append(patch)
    if not patches:
        raise RuntimeError("no annotation patches were available")
    return [
        [sum(p[y][x] for p in patches) / len(patches) for x in range(size)]
        for y in range(size)
    ]


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


def detect_vertices_template(img, template, radius=12, threshold=0.55):
    box, _ = magenta_box(img)
    pix = img.load()
    candidates = []
    for y in range(max(radius, box[1] - 25), min(img.height - radius, box[3] + 26)):
        for x in range(max(radius, box[0] - 25), min(img.width - radius, box[2] + 26)):
            score = normalized_template_score(pix, template, radius, x, y)
            if score >= threshold:
                candidates.append(Point(x, y, score))
    return sorted(suppress_close(candidates, 12), key=lambda p: p.score, reverse=True)


def process(path, template=None, radius=12, threshold=0.55):
    img = Image.open(path).convert("RGB")
    if template is None:
        vertices = detect_vertices(img)
    else:
        vertices = detect_vertices_template(img, template, radius, threshold)
    base, _ = os.path.splitext(path)
    out_path = base + "_vertex_lab.png"
    draw_vertices(img, vertices, out_path)
    print(f"{path}: vertices={len(vertices)} -> {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-pair", action="append", default=[], help="Training pair as image.png=annotation_vertices.png; can be repeated")
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    template = None
    if args.train_pair:
        pairs = []
        for item in args.train_pair:
            image_path, annotation_path = item.split("=", 1)
            pairs.append((image_path, annotation_path))
        template = build_template(pairs, 12)
        # Save the learned template beside the first training image for inspection.
        first_dir = os.path.dirname(pairs[0][0]) or "."
        tmin = min(min(row) for row in template)
        tmax = max(max(row) for row in template)
        preview = Image.new("L", (25, 25))
        for y in range(25):
            for x in range(25):
                preview.putpixel((x, y), int((template[y][x] - tmin) / (tmax - tmin) * 255))
        preview.resize((125, 125)).save(os.path.join(first_dir, "learned_vertex_template.png"))
    for path in args.paths:
        process(path, template, threshold=args.threshold)


if __name__ == "__main__":
    main()
