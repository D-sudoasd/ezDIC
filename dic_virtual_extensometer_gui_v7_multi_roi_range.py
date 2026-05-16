#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DIC Virtual Extensometer GUI v7 Multi-ROI Range Preview
-----------------------------------------
用途：
    只计算单轴拉伸平均应变，不做全场 DIC。
    支持添加多组 ROI pair，每组 ROI 独立追踪、独立输出应变曲线。

核心功能：
    1. 多组 ROI：可以添加 G01、G02、G03... 分别分析。
    2. 方向自动判断：auto 模式下，左右分开用 x，上下分开用 y，倾斜明显用 distance。
    3. 对齐辅助：
       - 水平对齐：强制 ROI1/ROI2 中心 y 相同，并建议用 x 应变。
       - 垂直对齐：强制 ROI1/ROI2 中心 x 相同，并建议用 y 应变。
       - 绘制 ROI2 时可自动对齐。
    4. 自适应追踪：
       - hard accept：相关系数高，应变增量连续。
       - adaptive accept：相关系数略低，但通过软阈值、应变连续、前后向检查。
       - rejected：不更新 ROI、不更新模板，应变写 NaN。
    5. Windows 中文路径兼容：使用 np.fromfile + cv2.imdecode 读取图片。
    6. 可预览任意帧，并设置分析起始帧/结束帧，方便避开无效前后段。

依赖：
    pip install opencv-python numpy pandas matplotlib pillow

运行：
    python dic_virtual_extensometer_gui_v7_multi_roi_range.py
"""

import os
import re
import math
import glob
import threading
import traceback
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk


APP_NAME = "ezDIC"
APP_VERSION = "0.1.0"
APP_DEVELOPER = "Dr. Delun Gong"
APP_TITLE = f"{APP_NAME} v{APP_VERSION} - Developed by {APP_DEVELOPER}"

USAGE_NOTICE = """ezDIC Attribution and Usage Notice

Developer:
Dr. Delun Gong

This software was developed by Dr. Delun Gong for lightweight extraction of linear strain from image sequences.

Users are not permitted to:
1. claim that they developed this software;
2. remove or alter the developer attribution;
3. redistribute, copy, forward, or share this software with unauthorized users;
4. use this software outside the authorized research or teaching context.

If you need to share or reuse this software, please obtain permission from Dr. Delun Gong first.
"""


IMAGE_EXTENSIONS = [
    "*.tif", "*.tiff", "*.TIF", "*.TIFF",
    "*.png", "*.jpg", "*.jpeg", "*.bmp"
]

TRACKING_PRESETS = {
    "标准": {
        "search_radius": 180,
        "hard_corr": 0.55,
        "soft_corr": 0.35,
        "max_frame_strain_jump": "0.01",
        "fb_tolerance_px": 12.0,
    },
    "低质量图像": {
        "search_radius": 220,
        "hard_corr": 0.45,
        "soft_corr": 0.30,
        "max_frame_strain_jump": "0.015",
        "fb_tolerance_px": 16.0,
    },
    "快速变形": {
        "search_radius": 300,
        "hard_corr": 0.50,
        "soft_corr": 0.30,
        "max_frame_strain_jump": "0.03",
        "fb_tolerance_px": 20.0,
    },
}

STRAIN_MODE_LABEL_TO_VALUE = {
    "自动判断": "auto",
    "横向应变": "x",
    "纵向应变": "y",
    "两点距离应变": "distance",
}
STRAIN_MODE_VALUE_TO_LABEL = {v: k for k, v in STRAIN_MODE_LABEL_TO_VALUE.items()}


# ==========================
# 基础函数
# ==========================

def natural_sort_key(s):
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split(r"(\d+)", str(s))
    ]


def safe_name(s):
    s = str(s).strip()
    if not s:
        return "group"
    s = re.sub(r"[^\w\-.]+", "_", s, flags=re.UNICODE)
    return s[:80]


def collect_images(folder):
    paths = []
    for ext in IMAGE_EXTENSIONS:
        paths.extend(glob.glob(os.path.join(folder, ext)))
    return sorted(list(set(paths)), key=natural_sort_key)


def read_gray_image(path):
    """
    稳健读取图像。
    使用 np.fromfile + cv2.imdecode 解决 Windows 中文路径问题；
    如果失败则用 Pillow 兜底读取。
    """
    path = str(path)
    img = None
    errors = []

    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size > 0:
            img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception as exc:
        errors.append(f"cv2.imdecode failed: {exc}")

    if img is None:
        try:
            with Image.open(path) as im:
                if getattr(im, "n_frames", 1) > 1:
                    im.seek(0)
                img = np.array(im)
        except Exception as exc:
            errors.append(f"Pillow failed: {exc}")

    if img is None:
        detail = " | ".join(errors) if errors else "unknown error"
        raise RuntimeError(f"无法读取图片：{path}\n原因：{detail}")

    if img.ndim == 3:
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if img.ndim == 3 and img.shape[2] == 1:
        img = img[:, :, 0]

    return img


def normalize_to_uint8(img, lo=None, hi=None):
    arr = img.astype(np.float32)

    if lo is None or hi is None:
        lo, hi = np.percentile(arr, [1, 99])

    if hi <= lo:
        hi = lo + 1.0

    out = np.clip((arr - lo) / (hi - lo), 0, 1)
    return (out * 255).astype(np.uint8)


def get_display_image(img8, max_w=1120, max_h=720):
    h, w = img8.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)

    if scale < 1:
        disp = cv2.resize(img8, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    else:
        disp = img8.copy()

    rgb = cv2.cvtColor(disp, cv2.COLOR_GRAY2RGB)
    return rgb, scale


def rect_normalize(x1, y1, x2, y2):
    x = min(x1, x2)
    y = min(y1, y2)
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    return int(round(x)), int(round(y)), int(round(w)), int(round(h))


def clamp_rect(rect, img_shape):
    x, y, w, h = rect
    H, W = img_shape[:2]

    x = max(0, min(int(round(x)), W - 1))
    y = max(0, min(int(round(y)), H - 1))
    w = max(1, min(int(round(w)), W - x))
    h = max(1, min(int(round(h)), H - y))
    return x, y, w, h


def rect_center(rect):
    x, y, w, h = rect
    return float(x + w / 2.0), float(y + h / 2.0)


def move_rect_center(rect, new_cx=None, new_cy=None, img_shape=None):
    x, y, w, h = rect
    cx, cy = rect_center(rect)
    if new_cx is None:
        new_cx = cx
    if new_cy is None:
        new_cy = cy

    new_x = int(round(new_cx - w / 2.0))
    new_y = int(round(new_cy - h / 2.0))
    out = (new_x, new_y, w, h)
    if img_shape is not None:
        out = clamp_rect(out, img_shape)
    return out


def center_distance(rect_a, rect_b):
    ax, ay = rect_center(rect_a)
    bx, by = rect_center(rect_b)
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def roi_separation(rect1, rect2):
    x1, y1 = rect_center(rect1)
    x2, y2 = rect_center(rect2)
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    dist = math.sqrt(dx ** 2 + dy ** 2)
    return dx, dy, dist


def resolve_strain_mode(rect1, rect2, selected_mode):
    """
    自动判断应变方向：
    - 左右分开明显：x
    - 上下分开明显：y
    - 倾斜明显：distance
    """
    if selected_mode != "auto":
        return selected_mode

    dx, dy, dist = roi_separation(rect1, rect2)

    if dx >= 3.0 * max(dy, 1.0):
        return "x"
    if dy >= 3.0 * max(dx, 1.0):
        return "y"
    return "distance"


def length_between(rect1, rect2, mode="x"):
    x1, y1 = rect_center(rect1)
    x2, y2 = rect_center(rect2)

    if mode == "y":
        return abs(y2 - y1)
    if mode == "x":
        return abs(x2 - x1)
    if mode == "distance":
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    raise ValueError("应变方向只能是 x, y 或 distance。")


def extract_patch(img8, rect):
    x, y, w, h = clamp_rect(rect, img8.shape)
    return img8[y:y + h, x:x + w].astype(np.float32)


def roi_texture_metrics(img8, rect):
    patch = extract_patch(img8, rect)
    if patch.size == 0:
        return {
            "std_gray": 0.0,
            "contrast_p95_p5": 0.0,
            "low_frac": 1.0,
            "high_frac": 1.0,
        }

    p5, p95 = np.percentile(patch, [5, 95])
    return {
        "std_gray": float(np.std(patch)),
        "contrast_p95_p5": float(p95 - p5),
        "low_frac": float(np.mean(patch <= 5)),
        "high_frac": float(np.mean(patch >= 250)),
    }


def texture_is_ok(metrics, min_std, min_contrast, max_saturated_frac):
    if metrics["std_gray"] < min_std:
        return False
    if metrics["contrast_p95_p5"] < min_contrast:
        return False
    if metrics["low_frac"] > max_saturated_frac:
        return False
    if metrics["high_frac"] > max_saturated_frac:
        return False
    return True


def subpixel_peak(corr, px, py):
    H, W = corr.shape
    dx = 0.0
    dy = 0.0

    if 1 <= px < W - 1:
        c1 = corr[py, px - 1]
        c2 = corr[py, px]
        c3 = corr[py, px + 1]
        denom = c1 - 2 * c2 + c3
        if abs(denom) > 1e-12:
            dx = 0.5 * (c1 - c3) / denom

    if 1 <= py < H - 1:
        c1 = corr[py - 1, px]
        c2 = corr[py, px]
        c3 = corr[py + 1, px]
        denom = c1 - 2 * c2 + c3
        if abs(denom) > 1e-12:
            dy = 0.5 * (c1 - c3) / denom

    return float(np.clip(dx, -0.5, 0.5)), float(np.clip(dy, -0.5, 0.5))


def match_template_candidate(img8, last_rect, template, search_radius):
    H, W = img8.shape[:2]
    x, y, w, h = last_rect
    x = float(x)
    y = float(y)
    w = int(round(w))
    h = int(round(h))

    sx1 = int(max(0, math.floor(x - search_radius)))
    sy1 = int(max(0, math.floor(y - search_radius)))
    sx2 = int(min(W, math.ceil(x + w + search_radius)))
    sy2 = int(min(H, math.ceil(y + h + search_radius)))

    search_img = img8[sy1:sy2, sx1:sx2].astype(np.float32)

    if search_img.shape[0] < h or search_img.shape[1] < w:
        return last_rect, -1.0

    if template.shape[0] != h or template.shape[1] != w:
        return last_rect, -1.0

    corr = cv2.matchTemplate(search_img, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(corr)

    px, py = max_loc
    dx, dy = subpixel_peak(corr, px, py)

    new_x = sx1 + px + dx
    new_y = sy1 + py + dy

    return (float(new_x), float(new_y), w, h), float(max_val)


def update_template_from_rect(img8, rect, old_template, alpha):
    x, y, w, h = rect
    x = int(round(x))
    y = int(round(y))
    w = int(round(w))
    h = int(round(h))

    H, W = img8.shape[:2]
    if x < 0 or y < 0 or x + w > W or y + h > H:
        return old_template

    patch = img8[y:y + h, x:x + w].astype(np.float32)
    if patch.shape != old_template.shape:
        return old_template

    return (1.0 - alpha) * old_template + alpha * patch


def forward_backward_error(prev_img8, curr_img8, prev_rect, curr_candidate_rect, search_radius):
    """
    前后向一致性检查：
    curr 候选位置若真实，应能用当前 patch 反追踪回 prev_rect。
    """
    curr_patch = extract_patch(curr_img8, curr_candidate_rect)
    back_rect, back_score = match_template_candidate(
        prev_img8,
        prev_rect,
        curr_patch,
        search_radius=search_radius,
    )
    err = center_distance(back_rect, prev_rect)
    return float(err), float(back_score)


def draw_group_overlay(
    img8,
    group_name,
    actual_mode,
    used_rect1,
    used_rect2,
    candidate_rect1,
    candidate_rect2,
    frame_idx,
    strain,
    last_valid_strain,
    score1,
    score2,
    accepted,
    accept_mode,
    reason,
    fb_err1=None,
    fb_err2=None,
):
    rgb = cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR)

    def draw_rect(rect, color, label, thickness=2):
        if rect is None:
            return
        x, y, w, h = rect
        x = int(round(x))
        y = int(round(y))
        w = int(round(w))
        h = int(round(h))

        cv2.rectangle(rgb, (x, y), (x + w, y + h), color, thickness)
        cx = int(round(x + w / 2.0))
        cy = int(round(y + h / 2.0))
        cv2.circle(rgb, (cx, cy), 4, color, -1)
        cv2.putText(
            rgb,
            label,
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )

    # 候选框：橙/紫
    draw_rect(candidate_rect1, (0, 165, 255), "ROI1 candidate", 1)
    draw_rect(candidate_rect2, (255, 0, 255), "ROI2 candidate", 1)

    # 实际用于计算的框：红/蓝
    draw_rect(used_rect1, (0, 0, 255), "ROI1 used", 2)
    draw_rect(used_rect2, (255, 0, 0), "ROI2 used", 2)

    c1 = rect_center(used_rect1)
    c2 = rect_center(used_rect2)
    cv2.line(
        rgb,
        (int(round(c1[0])), int(round(c1[1]))),
        (int(round(c2[0])), int(round(c2[1]))),
        (0, 255, 255),
        2,
    )

    status = "ACCEPTED" if accepted else "REJECTED - ROI/TEMPLATE NOT UPDATED"
    if accepted and accept_mode:
        status += f" ({accept_mode})"

    strain_txt = f"Eng. strain: {strain:.6f}" if np.isfinite(strain) else "Eng. strain: NaN"
    last_txt = f"Last valid strain: {last_valid_strain:.6f}" if np.isfinite(last_valid_strain) else "Last valid strain: NaN"

    lines = [
        f"Group: {group_name} | mode: {actual_mode}",
        f"Frame: {frame_idx}",
        status,
        strain_txt,
        last_txt,
        f"Corr: ROI1={score1:.3f}, ROI2={score2:.3f}",
    ]

    if fb_err1 is not None and fb_err2 is not None:
        lines.append(f"FB error: ROI1={fb_err1:.2f}px, ROI2={fb_err2:.2f}px")

    lines.append(f"Reason: {reason}")

    y0 = 34
    for k, line in enumerate(lines):
        cv2.putText(
            rgb,
            line[:140],
            (20, y0 + 30 * k),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68 if k < 3 else 0.56,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

    return rgb


def _frame_column(df):
    if "frame_global_1based" in df.columns:
        return "frame_global_1based"
    if "frame_local_1based" in df.columns:
        return "frame_local_1based"
    return "frame"


def _format_origin_float(value):
    if pd.isna(value) or not np.isfinite(float(value)):
        return "NaN"
    return f"{float(value):.8f}"


def build_core_strain_table(gdf):
    """
    Build the minimal Origin-friendly strain table:
    Frame, EngineeringStrain, TrueStrain.
    True strain is recomputed from engineering strain to keep export logic explicit.
    """
    frame_col = _frame_column(gdf)
    frames = pd.to_numeric(gdf[frame_col], errors="coerce")
    eng = pd.to_numeric(gdf["engineering_strain"], errors="coerce")

    true_values = []
    for value in eng:
        if pd.isna(value) or not np.isfinite(float(value)) or (1.0 + float(value)) <= 0:
            true_values.append(np.nan)
        else:
            true_values.append(math.log1p(float(value)))

    out = pd.DataFrame(
        {
            "Frame": frames.astype("Int64"),
            "EngineeringStrain": eng.astype(float),
            "TrueStrain": np.array(true_values, dtype=float),
        }
    )
    return out.reset_index(drop=True)


def write_origin_txt(gdf, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = build_core_strain_table(gdf)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("Frame\tEngineeringStrain\tTrueStrain\n")
        for _, row in table.iterrows():
            frame = "NaN" if pd.isna(row["Frame"]) else str(int(row["Frame"]))
            f.write(
                f"{frame}\t"
                f"{_format_origin_float(row['EngineeringStrain'])}\t"
                f"{_format_origin_float(row['TrueStrain'])}\n"
            )


def build_all_groups_strain_table(df):
    tables = []
    for gname, gdf in df.groupby("group", sort=False):
        sg = safe_name(gname)
        table = build_core_strain_table(gdf).rename(
            columns={
                "EngineeringStrain": f"EngineeringStrain_{sg}",
                "TrueStrain": f"TrueStrain_{sg}",
            }
        )
        tables.append(table)

    if not tables:
        return pd.DataFrame(columns=["Frame"])

    merged = tables[0]
    for table in tables[1:]:
        merged = pd.merge(merged, table, on="Frame", how="outer")
    return merged.sort_values("Frame").reset_index(drop=True)


def write_all_groups_origin_txt(df, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = build_all_groups_strain_table(df)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(table.columns) + "\n")
        for _, row in table.iterrows():
            values = []
            for col in table.columns:
                if col == "Frame":
                    values.append("NaN" if pd.isna(row[col]) else str(int(row[col])))
                else:
                    values.append(_format_origin_float(row[col]))
            f.write("\t".join(values) + "\n")


def plot_engineering_strain(gdf, path, title):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    table = build_core_strain_table(gdf)
    frame = table["Frame"].astype(float)
    strain = table["EngineeringStrain"].astype(float)
    accepted = gdf["accepted"].astype(bool).reset_index(drop=True) if "accepted" in gdf.columns else strain.notna()
    accept_mode = gdf["accept_mode"].astype(str).reset_index(drop=True) if "accept_mode" in gdf.columns else pd.Series([""] * len(gdf))

    rejected_mask = (~accepted) | strain.isna()
    adaptive_mask = accept_mode.eq("adaptive") & (~rejected_mask) & strain.notna()
    normal_mask = (~rejected_mask) & (~adaptive_mask) & strain.notna()

    plt.figure(figsize=(7, 5))
    plt.plot(frame, strain, color="#1f77b4", linewidth=1, alpha=0.65)
    plt.scatter(frame[normal_mask], strain[normal_mask], color="#1f77b4", s=18, label="Accepted")

    if adaptive_mask.any():
        plt.scatter(frame[adaptive_mask], strain[adaptive_mask], color="#ff7f0e", s=30, label="Adaptive")

    if rejected_mask.any():
        finite_strain = strain[np.isfinite(strain)]
        if len(finite_strain) > 0:
            ymin = float(finite_strain.min())
            ymax = float(finite_strain.max())
            span = ymax - ymin if ymax > ymin else max(abs(ymax), 1e-6)
            rejected_y = np.full(int(rejected_mask.sum()), ymin - 0.08 * span)
        else:
            rejected_y = np.zeros(int(rejected_mask.sum()))
        plt.scatter(frame[rejected_mask], rejected_y, color="#d62728", marker="x", s=38, label="Rejected/NaN")

    plt.xlabel("Frame")
    plt.ylabel("Engineering strain")
    plt.title(title)
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()


def build_qc_summary(df):
    levels = {"Good": 0, "Warning": 1, "Poor": 2}
    groups = {}

    for gname, sub in df.groupby("group", sort=False):
        frames = int(len(sub))
        accepted = sub["accepted"].astype(bool) if "accepted" in sub.columns else pd.Series([True] * frames, index=sub.index)
        eng = pd.to_numeric(sub["engineering_strain"], errors="coerce")
        rejected_mask = (~accepted) | eng.isna()
        adaptive_mask = sub["accept_mode"].astype(str).eq("adaptive") if "accept_mode" in sub.columns else pd.Series([False] * frames, index=sub.index)

        rejected_frames = int(rejected_mask.sum())
        valid_frames = int(frames - rejected_frames)
        adaptive_frames = int((adaptive_mask & (~rejected_mask)).sum())

        corr1 = pd.to_numeric(sub["corr_score_roi1"], errors="coerce") if "corr_score_roi1" in sub.columns else pd.Series(dtype=float)
        corr2 = pd.to_numeric(sub["corr_score_roi2"], errors="coerce") if "corr_score_roi2" in sub.columns else pd.Series(dtype=float)
        mean_corr1 = float(corr1.mean()) if len(corr1.dropna()) else np.nan
        mean_corr2 = float(corr2.mean()) if len(corr2.dropna()) else np.nan

        valid_eng = eng.dropna()
        max_abs_strain = float(valid_eng.abs().max()) if len(valid_eng) else np.nan
        jumps = valid_eng.diff().abs().dropna()
        max_jump = float(jumps.max()) if len(jumps) else 0.0

        frame_col = _frame_column(sub)
        rejected_frame_list = [
            int(x) for x in pd.to_numeric(sub.loc[rejected_mask, frame_col], errors="coerce").dropna().tolist()
        ]

        rejected_ratio = rejected_frames / frames if frames else 0.0
        finite_means = [value for value in [mean_corr1, mean_corr2] if np.isfinite(value)]
        min_mean_corr = min(finite_means) if finite_means else np.nan
        if rejected_ratio > 0.05:
            qc_level = "Poor"
        elif rejected_frames > 0 or adaptive_frames > 0 or (np.isfinite(min_mean_corr) and min_mean_corr < 0.80):
            qc_level = "Warning"
        else:
            qc_level = "Good"

        groups[str(gname)] = {
            "frames": frames,
            "valid_frames": valid_frames,
            "rejected_frames": rejected_frames,
            "adaptive_accepted_frames": adaptive_frames,
            "mean_corr_roi1": mean_corr1,
            "mean_corr_roi2": mean_corr2,
            "max_abs_engineering_strain": max_abs_strain,
            "max_frame_strain_jump": max_jump,
            "rejected_frame_list": rejected_frame_list,
            "qc_level": qc_level,
        }

    overall_level = "Good"
    for item in groups.values():
        if levels[item["qc_level"]] > levels[overall_level]:
            overall_level = item["qc_level"]

    return {
        "overall": {
            "qc_level": overall_level,
            "groups": len(groups),
            "rejected_frames": int(sum(item["rejected_frames"] for item in groups.values())),
            "adaptive_accepted_frames": int(sum(item["adaptive_accepted_frames"] for item in groups.values())),
        },
        "groups": groups,
    }


def _format_qc_number(value, digits=3):
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return "NaN"
    return f"{float(value):.{digits}f}"


def write_qc_summary(summary, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("ezDIC QC Summary\n")
        f.write("================\n")
        f.write(f"Overall QC level: {summary['overall']['qc_level']}\n")
        f.write(f"Groups: {summary['overall']['groups']}\n")
        f.write(f"Rejected frames: {summary['overall']['rejected_frames']}\n")
        f.write(f"Adaptive accepted frames: {summary['overall']['adaptive_accepted_frames']}\n")

        for gname, item in summary["groups"].items():
            rejected_list = ", ".join(str(x) for x in item["rejected_frame_list"]) or "None"
            f.write(f"\n[{gname}]\n")
            f.write(f"Frames: {item['frames']}\n")
            f.write(f"Valid frames: {item['valid_frames']}\n")
            f.write(f"Rejected frames: {item['rejected_frames']}\n")
            f.write(f"Adaptive accepted frames: {item['adaptive_accepted_frames']}\n")
            f.write(f"Mean corr ROI1: {_format_qc_number(item['mean_corr_roi1'], 3)}\n")
            f.write(f"Mean corr ROI2: {_format_qc_number(item['mean_corr_roi2'], 3)}\n")
            f.write(f"Max abs engineering strain: {_format_qc_number(item['max_abs_engineering_strain'], 4)}\n")
            f.write(f"Max frame strain jump: {_format_qc_number(item['max_frame_strain_jump'], 4)}\n")
            f.write(f"Rejected frame list: {rejected_list}\n")
            f.write(f"QC level: {item['qc_level']}\n")


# ==========================
# GUI 主类
# ==========================

class MultiROIGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1440x980")

        self.image_folder = tk.StringVar()
        self.output_folder = tk.StringVar()

        self.search_radius = tk.IntVar(value=180)
        self.hard_corr = tk.DoubleVar(value=0.55)
        self.soft_corr = tk.DoubleVar(value=0.35)
        self.strain_mode = tk.StringVar(value="auto")
        self.strain_mode_display = tk.StringVar(value=STRAIN_MODE_VALUE_TO_LABEL["auto"])
        self.tracking_preset = tk.StringVar(value="标准")
        self.preset_status_var = tk.StringVar(value="当前追踪模式：标准")
        self._applying_preset = False

        self.enable_adaptive = tk.BooleanVar(value=True)
        self.use_prev_frame_template = tk.BooleanVar(value=True)
        self.template_alpha = tk.DoubleVar(value=0.70)
        self.max_frame_strain_jump = tk.StringVar(value="0.01")

        self.enable_fb_check = tk.BooleanVar(value=True)
        self.fb_tolerance_px = tk.DoubleVar(value=12.0)

        self.overlay_every = tk.IntVar(value=5)
        self.pixel_size_mm = tk.StringVar(value="")

        self.auto_align_roi2 = tk.BooleanVar(value=True)

        self.min_texture_std = tk.DoubleVar(value=8.0)
        self.min_texture_contrast = tk.DoubleVar(value=25.0)
        self.max_saturated_frac = tk.DoubleVar(value=0.20)
        self.advanced_visible = tk.BooleanVar(value=False)

        self.export_origin_txt = tk.BooleanVar(value=True)
        self.export_engineering_png = tk.BooleanVar(value=True)
        self.export_qc_summary = tk.BooleanVar(value=True)
        self.export_full_csv = tk.BooleanVar(value=False)
        self.export_corr_plot = tk.BooleanVar(value=False)
        self.export_overlays = tk.BooleanVar(value=False)
        self.export_parameters = tk.BooleanVar(value=False)

        self.image_paths = []
        self.first_raw = None
        self.first_img8 = None  # 当前预览帧的 8-bit 图像，用于显示、画 ROI、纹理检查
        self.display_img = None
        self.display_scale = 1.0
        self.photo = None

        self.preview_frame_1based = tk.IntVar(value=1)
        self.start_frame_1based = tk.IntVar(value=1)
        self.end_frame_1based = tk.IntVar(value=1)
        self.current_preview_index = 0  # 0-based

        self.roi1 = None
        self.roi2 = None
        self.current_roi_index = 1
        self.drag_start = None
        self.temp_rect_id = None

        self.roi_groups = []
        self.next_group_idx = 1
        self.group_name_var = tk.StringVar(value="")

        self.is_processing = False

        for var in [
            self.search_radius,
            self.hard_corr,
            self.soft_corr,
            self.max_frame_strain_jump,
            self.fb_tolerance_px,
            self.template_alpha,
            self.min_texture_std,
            self.min_texture_contrast,
            self.max_saturated_frac,
        ]:
            var.trace_add("write", self.mark_tracking_custom)

        self.build_ui()

    # ---------- UI ----------

    def build_ui(self):
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        file_frame = ttk.LabelFrame(main, text="1. 图像与输出", padding=8)
        file_frame.pack(fill=tk.X, side=tk.TOP)

        ttk.Label(file_frame, text="图像文件夹：").grid(row=0, column=0, sticky="w")
        ttk.Entry(file_frame, textvariable=self.image_folder, width=92).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Button(file_frame, text="选择文件夹", command=self.select_image_folder).grid(row=0, column=2, padx=4)

        ttk.Label(file_frame, text="输出文件夹：").grid(row=1, column=0, sticky="w")
        ttk.Entry(file_frame, textvariable=self.output_folder, width=92).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Button(file_frame, text="选择输出", command=self.select_output_folder).grid(row=1, column=2, padx=4)

        seq_buttons = ttk.Frame(file_frame)
        seq_buttons.grid(row=2, column=0, columnspan=3, sticky="we", pady=(8, 0))
        ttk.Button(seq_buttons, text="加载图像序列", command=self.load_first_image).pack(side=tk.LEFT, padx=3)
        ttk.Label(seq_buttons, text="预览帧：").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Entry(seq_buttons, textvariable=self.preview_frame_1based, width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(seq_buttons, text="显示", command=self.go_to_preview_frame).pack(side=tk.LEFT, padx=2)
        ttk.Button(seq_buttons, text="上一帧", command=lambda: self.step_preview_frame(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(seq_buttons, text="下一帧", command=lambda: self.step_preview_frame(1)).pack(side=tk.LEFT, padx=2)
        ttk.Label(seq_buttons, text="分析范围：").pack(side=tk.LEFT, padx=(14, 2))
        ttk.Entry(seq_buttons, textvariable=self.start_frame_1based, width=7).pack(side=tk.LEFT, padx=2)
        ttk.Label(seq_buttons, text="到").pack(side=tk.LEFT)
        ttk.Entry(seq_buttons, textvariable=self.end_frame_1based, width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(seq_buttons, text="当前帧设为起始/参考", command=self.set_start_to_current).pack(side=tk.LEFT, padx=3)
        ttk.Button(seq_buttons, text="当前帧设为结束", command=self.set_end_to_current).pack(side=tk.LEFT, padx=3)
        file_frame.columnconfigure(1, weight=1)

        measure_frame = ttk.LabelFrame(main, text="2. 测量设置", padding=8)
        measure_frame.pack(fill=tk.X, side=tk.TOP, pady=(8, 0))

        ttk.Label(measure_frame, text="应变方向").grid(row=0, column=0, sticky="w")
        mode_box = ttk.Combobox(
            measure_frame,
            textvariable=self.strain_mode_display,
            values=list(STRAIN_MODE_LABEL_TO_VALUE.keys()),
            width=14,
            state="readonly",
        )
        mode_box.grid(row=0, column=1, padx=(3, 16), sticky="w")
        mode_box.bind("<<ComboboxSelected>>", self.sync_strain_mode_from_display)

        ttk.Label(measure_frame, text="追踪模式").grid(row=0, column=2, sticky="w")
        preset_box = ttk.Combobox(
            measure_frame,
            textvariable=self.tracking_preset,
            values=list(TRACKING_PRESETS.keys()) + ["自定义"],
            width=14,
            state="readonly",
        )
        preset_box.grid(row=0, column=3, padx=(3, 16), sticky="w")
        preset_box.bind("<<ComboboxSelected>>", self.apply_tracking_preset)
        ttk.Label(measure_frame, textvariable=self.preset_status_var).grid(row=0, column=4, padx=(0, 16), sticky="w")

        ttk.Label(measure_frame, text="像素尺寸 mm/px，可空").grid(row=0, column=5, sticky="w")
        ttk.Entry(measure_frame, textvariable=self.pixel_size_mm, width=10).grid(row=0, column=6, padx=(3, 16), sticky="w")
        ttk.Checkbutton(measure_frame, text="绘制 ROI2 后自动对齐", variable=self.auto_align_roi2).grid(row=0, column=7, sticky="w")

        self.advanced_toggle_btn = ttk.Button(measure_frame, text="显示高级设置", command=self.toggle_advanced_settings)
        self.advanced_toggle_btn.grid(row=1, column=0, pady=(8, 0), sticky="w")

        self.advanced_frame = ttk.LabelFrame(measure_frame, text="高级设置", padding=6)
        self.advanced_frame.grid(row=2, column=0, columnspan=8, sticky="we", pady=(8, 0))

        ttk.Label(self.advanced_frame, text="搜索半径 px").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.advanced_frame, textvariable=self.search_radius, width=7).grid(row=0, column=1, padx=(3, 10))
        ttk.Label(self.advanced_frame, text="严格接受阈值").grid(row=0, column=2, sticky="w")
        ttk.Entry(self.advanced_frame, textvariable=self.hard_corr, width=7).grid(row=0, column=3, padx=(3, 10))
        ttk.Label(self.advanced_frame, text="弱接受阈值").grid(row=0, column=4, sticky="w")
        ttk.Entry(self.advanced_frame, textvariable=self.soft_corr, width=7).grid(row=0, column=5, padx=(3, 10))
        ttk.Label(self.advanced_frame, text="单帧应变突变上限").grid(row=0, column=6, sticky="w")
        ttk.Entry(self.advanced_frame, textvariable=self.max_frame_strain_jump, width=8).grid(row=0, column=7, padx=(3, 10))

        ttk.Checkbutton(self.advanced_frame, text="启用自适应弱接受", variable=self.enable_adaptive).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(self.advanced_frame, text="使用前一帧模板跟随", variable=self.use_prev_frame_template).grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(self.advanced_frame, text="模板跟随系数").grid(row=1, column=4, sticky="w", pady=(6, 0))
        ttk.Entry(self.advanced_frame, textvariable=self.template_alpha, width=7).grid(row=1, column=5, padx=(3, 10), pady=(6, 0))
        ttk.Checkbutton(self.advanced_frame, text="前后向一致性检查", variable=self.enable_fb_check).grid(row=1, column=6, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(self.advanced_frame, text="FB 容差 px").grid(row=1, column=8, sticky="w", pady=(6, 0))
        ttk.Entry(self.advanced_frame, textvariable=self.fb_tolerance_px, width=7).grid(row=1, column=9, padx=(3, 10), pady=(6, 0))

        ttk.Label(self.advanced_frame, text="最小灰度标准差").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self.advanced_frame, textvariable=self.min_texture_std, width=8).grid(row=2, column=1, padx=(3, 10), pady=(6, 0))
        ttk.Label(self.advanced_frame, text="最小 P95-P5 对比度").grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(self.advanced_frame, textvariable=self.min_texture_contrast, width=8).grid(row=2, column=3, padx=(3, 10), pady=(6, 0))
        ttk.Label(self.advanced_frame, text="最大近黑/近白比例").grid(row=2, column=4, sticky="w", pady=(6, 0))
        ttk.Entry(self.advanced_frame, textvariable=self.max_saturated_frac, width=8).grid(row=2, column=5, padx=(3, 10), pady=(6, 0))
        ttk.Label(self.advanced_frame, text="overlay 间隔").grid(row=2, column=6, sticky="w", pady=(6, 0))
        ttk.Entry(self.advanced_frame, textvariable=self.overlay_every, width=7).grid(row=2, column=7, padx=(3, 10), pady=(6, 0))
        self.advanced_frame.grid_remove()

        group_frame = ttk.LabelFrame(main, text="3. ROI 设置", padding=6)
        group_frame.pack(fill=tk.X, side=tk.TOP, pady=(8, 0))

        buttons = ttk.Frame(group_frame)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="画 ROI 1", command=lambda: self.set_roi_mode(1)).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="画 ROI 2", command=lambda: self.set_roi_mode(2)).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="水平对齐→横向应变", command=lambda: self.align_current_pair("x", set_mode=True)).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="垂直对齐→纵向应变", command=lambda: self.align_current_pair("y", set_mode=True)).pack(side=tk.LEFT, padx=3)
        ttk.Label(buttons, text="组名：").pack(side=tk.LEFT, padx=(14, 2))
        ttk.Entry(buttons, textvariable=self.group_name_var, width=14).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="添加当前 ROI 为一组", command=self.add_current_group).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="更新选中组", command=self.update_selected_group).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="载入选中组", command=self.load_selected_group).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="删除选中组", command=self.delete_selected_group).pack(side=tk.LEFT, padx=3)
        ttk.Button(buttons, text="清除当前 ROI", command=self.clear_current_rois).pack(side=tk.LEFT, padx=3)

        columns = ("name", "selected", "actual", "L0", "dx", "dy", "roi1", "roi2")
        self.group_tree = ttk.Treeview(group_frame, columns=columns, show="headings", height=4)
        for col, width in [
            ("name", 90), ("selected", 70), ("actual", 70), ("L0", 90),
            ("dx", 90), ("dy", 90), ("roi1", 210), ("roi2", 210)
        ]:
            self.group_tree.heading(col, text=col)
            self.group_tree.column(col, width=width, anchor="center")
        self.group_tree.pack(fill=tk.X, pady=(6, 0))
        self.group_tree.bind("<Double-1>", lambda event: self.load_selected_group())

        middle = ttk.Frame(main)
        middle.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        image_frame = ttk.LabelFrame(middle, text="图像区：拖动画当前 ROI；绿色线为已添加的 ROI 组", padding=4)
        image_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(image_frame, bg="#202020", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

        side = ttk.LabelFrame(middle, text="4. 分析与导出", padding=8)
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        instruction = (
            "推荐流程：加载图像 → 设起止帧 → 选择方向和追踪模式 → "
            "画 ROI1/ROI2 → 添加 ROI 组 → 开始分析。\n\n"
            "默认只导出 Origin TXT、工程应变图和 QC 摘要；完整 CSV、相关系数图、"
            "overlay 和参数文件按需勾选。"
        )
        ttk.Label(side, text=instruction, justify=tk.LEFT, width=50, wraplength=380).pack(anchor="nw")
        ttk.Label(
            side,
            text=f"Developed by {APP_DEVELOPER}",
            foreground="#555555",
        ).pack(anchor="w", pady=(6, 0))
        ttk.Button(side, text="About / Usage Notice", command=self.show_usage_notice).pack(fill=tk.X, pady=(8, 0))

        ttk.Separator(side).pack(fill=tk.X, pady=8)

        export_frame = ttk.LabelFrame(side, text="导出内容", padding=6)
        export_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(export_frame, text="Origin TXT（三列核心数据）", variable=self.export_origin_txt).pack(anchor="w")
        ttk.Checkbutton(export_frame, text="工程应变 PNG", variable=self.export_engineering_png).pack(anchor="w")
        ttk.Checkbutton(export_frame, text="QC 摘要 TXT", variable=self.export_qc_summary).pack(anchor="w")
        ttk.Checkbutton(export_frame, text="完整 CSV（含 ROI 坐标历史）", variable=self.export_full_csv).pack(anchor="w")
        ttk.Checkbutton(export_frame, text="相关系数曲线 PNG", variable=self.export_corr_plot).pack(anchor="w")
        ttk.Checkbutton(export_frame, text="追踪 overlay 图片", variable=self.export_overlays).pack(anchor="w")
        ttk.Checkbutton(export_frame, text="参数与详细接受统计", variable=self.export_parameters).pack(anchor="w")

        ttk.Button(side, text="开始分析并导出", command=self.start_processing).pack(fill=tk.X, pady=(0, 8))

        self.progress = ttk.Progressbar(side, orient=tk.HORIZONTAL, mode="determinate", length=360)
        self.progress.pack(fill=tk.X, pady=(0, 6))

        self.status_var = tk.StringVar(value="未加载图像")
        ttk.Label(side, textvariable=self.status_var, wraplength=380).pack(anchor="w", pady=(0, 6))

        self.log_text = tk.Text(side, width=56, height=26, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def sync_strain_mode_from_display(self, event=None):
        label = self.strain_mode_display.get()
        self.strain_mode.set(STRAIN_MODE_LABEL_TO_VALUE.get(label, "auto"))

    def sync_strain_mode_display(self):
        value = self.strain_mode.get()
        self.strain_mode_display.set(STRAIN_MODE_VALUE_TO_LABEL.get(value, "自动判断"))

    def apply_tracking_preset(self, event=None):
        name = self.tracking_preset.get()
        preset = TRACKING_PRESETS.get(name)
        if not preset:
            return

        self._applying_preset = True
        try:
            self.search_radius.set(preset["search_radius"])
            self.hard_corr.set(preset["hard_corr"])
            self.soft_corr.set(preset["soft_corr"])
            self.max_frame_strain_jump.set(preset["max_frame_strain_jump"])
            self.fb_tolerance_px.set(preset["fb_tolerance_px"])
        finally:
            self._applying_preset = False

        self.preset_status_var.set(f"当前追踪模式：{name}")
        if hasattr(self, "status_var"):
            self.status_var.set(f"当前追踪模式：{name}")

    def mark_tracking_custom(self, *args):
        if getattr(self, "_applying_preset", False):
            return
        if not hasattr(self, "preset_status_var"):
            return
        if self.tracking_preset.get() != "自定义":
            self.tracking_preset.set("自定义")
        self.preset_status_var.set("当前追踪模式：自定义")

    def toggle_advanced_settings(self):
        if self.advanced_visible.get():
            self.advanced_frame.grid_remove()
            self.advanced_visible.set(False)
            self.advanced_toggle_btn.config(text="显示高级设置")
        else:
            self.advanced_frame.grid()
            self.advanced_visible.set(True)
            self.advanced_toggle_btn.config(text="隐藏高级设置")

    def show_usage_notice(self):
        messagebox.showinfo("About / Usage Notice", USAGE_NOTICE)

    # ---------- 日志和文件 ----------

    def log(self, msg):
        self.log_text.insert(tk.END, str(msg) + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def select_image_folder(self):
        folder = filedialog.askdirectory(title="选择 TIF 图片文件夹")
        if folder:
            self.image_folder.set(folder)
            self.output_folder.set(os.path.join(folder, "virtual_extensometer_output_v7_multi_roi_range"))
            self.log(f"图像文件夹：{folder}")

    def select_output_folder(self):
        folder = filedialog.askdirectory(title="选择输出文件夹")
        if folder:
            self.output_folder.set(folder)
            self.log(f"输出文件夹：{folder}")

    def load_first_image(self):
        """
        加载图像序列，并显示当前 preview_frame_1based 指定的帧。
        保留函数名是为了兼容前面按钮调用。
        """
        folder = self.image_folder.get().strip()
        if not folder:
            messagebox.showwarning("缺少文件夹", "请先选择图像文件夹。")
            return

        self.image_paths = collect_images(folder)
        if not self.image_paths:
            messagebox.showerror("未找到图像", "该文件夹中没有找到 tif/tiff/png/jpg/bmp 图像。")
            return

        n = len(self.image_paths)

        # 如果用户还没设置范围，默认 1 到最后一帧。
        if self.end_frame_1based.get() <= 1:
            self.end_frame_1based.set(n)

        self.preview_frame_1based.set(max(1, min(self.preview_frame_1based.get(), n)))
        self.start_frame_1based.set(max(1, min(self.start_frame_1based.get(), n)))
        self.end_frame_1based.set(max(1, min(self.end_frame_1based.get(), n)))

        try:
            self.load_preview_frame(self.preview_frame_1based.get() - 1)
            self.log(f"找到 {n} 张图像。")
            self.log(f"当前预览：第 {self.current_preview_index + 1} 帧 / 共 {n} 帧")
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))
            self.log(traceback.format_exc())

    def load_preview_frame(self, index0):
        if not self.image_paths:
            raise RuntimeError("请先加载图像序列。")

        n = len(self.image_paths)
        index0 = int(max(0, min(index0, n - 1)))

        self.current_preview_index = index0
        self.preview_frame_1based.set(index0 + 1)

        path = self.image_paths[index0]
        self.first_raw = read_gray_image(path)
        self.first_img8 = normalize_to_uint8(self.first_raw)
        self.display_img, self.display_scale = get_display_image(self.first_img8)

        self.show_image()
        self.status_var.set(
            f"预览第 {index0 + 1}/{n} 帧：{os.path.basename(path)} | "
            f"分析范围 {self.start_frame_1based.get()}–{self.end_frame_1based.get()}"
        )
        self.log(f"已显示第 {index0 + 1} 帧：{path}")
        self.log(f"图像尺寸：{self.first_img8.shape[1]} × {self.first_img8.shape[0]} px")

    def go_to_preview_frame(self):
        if not self.image_paths:
            self.load_first_image()
            return

        try:
            idx = int(self.preview_frame_1based.get()) - 1
            self.load_preview_frame(idx)
        except Exception as exc:
            messagebox.showerror("预览失败", str(exc))
            self.log(traceback.format_exc())

    def step_preview_frame(self, step):
        if not self.image_paths:
            self.load_first_image()
            return

        try:
            self.load_preview_frame(self.current_preview_index + int(step))
        except Exception as exc:
            messagebox.showerror("预览失败", str(exc))
            self.log(traceback.format_exc())

    def clear_groups_if_start_changes(self, new_start_1based):
        old_start = self.start_frame_1based.get()
        if new_start_1based == old_start:
            return True

        if self.roi_groups:
            msg = (
                f"你已经添加了 {len(self.roi_groups)} 组 ROI。\\n\\n"
                f"这些 ROI 应该是在当前起始/参考帧第 {old_start} 帧上定义的。\\n"
                f"如果把起始/参考帧改为第 {new_start_1based} 帧，已有 ROI 模板可能不再对应。\\n\\n"
                f"建议清空已有 ROI 组并在新起始帧上重画。是否清空并修改起始帧？"
            )
            if not messagebox.askyesno("修改起始/参考帧", msg):
                return False
            self.roi_groups.clear()
            self.refresh_group_tree()
            self.log("由于修改起始/参考帧，已清空已有 ROI 组。")
        return True

    def set_start_to_current(self):
        if not self.image_paths:
            messagebox.showwarning("未加载图像", "请先加载图像序列。")
            return

        new_start = self.current_preview_index + 1
        if not self.clear_groups_if_start_changes(new_start):
            return

        self.start_frame_1based.set(new_start)
        if self.end_frame_1based.get() < new_start:
            self.end_frame_1based.set(len(self.image_paths))
        self.log(f"已将第 {new_start} 帧设为分析起始/参考帧。请在这张图上画 ROI。")
        self.status_var.set(f"起始/参考帧 = {new_start}；结束帧 = {self.end_frame_1based.get()}")

    def set_end_to_current(self):
        if not self.image_paths:
            messagebox.showwarning("未加载图像", "请先加载图像序列。")
            return

        end = self.current_preview_index + 1
        self.end_frame_1based.set(end)
        self.log(f"已将第 {end} 帧设为分析结束帧。")
        self.status_var.set(f"起始/参考帧 = {self.start_frame_1based.get()}；结束帧 = {end}")

    def get_analysis_indices(self):
        if not self.image_paths:
            raise RuntimeError("请先加载图像序列。")

        n = len(self.image_paths)
        s = int(self.start_frame_1based.get()) - 1
        e = int(self.end_frame_1based.get()) - 1

        s = max(0, min(s, n - 1))
        e = max(0, min(e, n - 1))

        if e < s:
            raise RuntimeError(
                f"分析结束帧不能早于起始帧：start={s + 1}, end={e + 1}"
            )

        return s, e

    # ---------- 图像显示与 ROI 绘制 ----------

    def show_image(self):
        if self.display_img is None:
            return

        pil_img = Image.fromarray(self.display_img)
        self.photo = ImageTk.PhotoImage(pil_img)

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.config(scrollregion=(0, 0, self.display_img.shape[1], self.display_img.shape[0]))

        self.redraw_rois_and_groups()

    def set_roi_mode(self, idx):
        self.current_roi_index = idx
        self.status_var.set(f"当前绘制：ROI {idx}。请在图中拖出矩形。")
        self.log(f"切换到绘制 ROI {idx}")

    def clear_current_rois(self):
        self.roi1 = None
        self.roi2 = None
        self.show_image()
        self.log("已清除当前 ROI。")

    def on_mouse_down(self, event):
        if self.first_img8 is None:
            return

        self.drag_start = (event.x, event.y)
        if self.temp_rect_id is not None:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None

    def on_mouse_drag(self, event):
        if self.drag_start is None:
            return

        x0, y0 = self.drag_start
        x1, y1 = event.x, event.y

        if self.temp_rect_id is not None:
            self.canvas.delete(self.temp_rect_id)

        color = "red" if self.current_roi_index == 1 else "cyan"
        self.temp_rect_id = self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=2)

    def on_mouse_up(self, event):
        if self.first_img8 is None or self.drag_start is None:
            return

        x0, y0 = self.drag_start
        x1, y1 = event.x, event.y
        self.drag_start = None

        if self.temp_rect_id is not None:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None

        inv = 1.0 / self.display_scale
        rx, ry, rw, rh = rect_normalize(x0 * inv, y0 * inv, x1 * inv, y1 * inv)

        if rw < 15 or rh < 15:
            messagebox.showwarning("ROI 太小", "ROI 太小。建议至少 30×30 px，且包含清晰散斑纹理。")
            return

        rect = clamp_rect((rx, ry, rw, rh), self.first_img8.shape)

        if self.current_roi_index == 1:
            self.roi1 = rect
            self.log(f"当前 ROI 1 = {rect}")
            self.log_roi_texture("当前 ROI 1", rect)
            self.current_roi_index = 2
            self.status_var.set("ROI 1 已设置。现在请绘制 ROI 2。")
        else:
            self.roi2 = rect
            if self.auto_align_roi2.get() and self.roi1 is not None:
                axis = self.auto_choose_alignment_axis()
                self.align_current_pair(axis, set_mode=False)
                self.log(f"ROI2 已按 {axis} 方向自动对齐。")
            else:
                self.log(f"当前 ROI 2 = {rect}")
                self.log_roi_texture("当前 ROI 2", rect)
            self.status_var.set("ROI 2 已设置。可以添加为一组。")

        self.show_image()

    def redraw_rois_and_groups(self):
        if self.display_img is None:
            return

        s = self.display_scale

        # 已添加组：绿色线和小标签
        for idx, group in enumerate(self.roi_groups, start=1):
            r1 = group["roi1"]
            r2 = group["roi2"]
            c1 = rect_center(r1)
            c2 = rect_center(r2)
            self.canvas.create_line(c1[0]*s, c1[1]*s, c2[0]*s, c2[1]*s, fill="lime", width=2)
            self.canvas.create_text(
                c1[0]*s + 4,
                c1[1]*s + 4,
                text=group["name"],
                anchor="nw",
                fill="lime",
                font=("Arial", 10, "bold"),
            )

        def draw(rect, color, label):
            if rect is None:
                return

            x, y, w, h = rect
            x1 = x * s
            y1 = y * s
            x2 = (x + w) * s
            y2 = (y + h) * s

            self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2)
            self.canvas.create_text(
                x1 + 5,
                y1 + 5,
                text=label,
                anchor="nw",
                fill=color,
                font=("Arial", 12, "bold"),
            )

        draw(self.roi1, "red", "current ROI 1")
        draw(self.roi2, "cyan", "current ROI 2")

    # ---------- 对齐与组管理 ----------

    def auto_choose_alignment_axis(self):
        """
        返回 'x' 或 'y'。
        x 表示水平对齐，使用 x 方向标距；
        y 表示垂直对齐，使用 y 方向标距。
        """
        selected = self.strain_mode.get()
        if selected in ("x", "y"):
            return selected

        if self.roi1 is None or self.roi2 is None:
            return "x"

        dx, dy, _ = roi_separation(self.roi1, self.roi2)
        return "x" if dx >= dy else "y"

    def align_current_pair(self, axis, set_mode=True):
        if self.first_img8 is None:
            messagebox.showwarning("未加载图像", "请先加载第一张图。")
            return
        if self.roi1 is None or self.roi2 is None:
            messagebox.showwarning("缺少 ROI", "请先画 ROI 1 和 ROI 2。")
            return

        c1x, c1y = rect_center(self.roi1)

        if axis == "x":
            self.roi2 = move_rect_center(self.roi2, new_cy=c1y, img_shape=self.first_img8.shape)
            if set_mode:
                self.strain_mode.set("x")
                self.sync_strain_mode_display()
            self.log("已水平对齐：ROI2 中心 y 已强制等于 ROI1 中心 y；建议使用横向应变。")
        elif axis == "y":
            self.roi2 = move_rect_center(self.roi2, new_cx=c1x, img_shape=self.first_img8.shape)
            if set_mode:
                self.strain_mode.set("y")
                self.sync_strain_mode_display()
            self.log("已垂直对齐：ROI2 中心 x 已强制等于 ROI1 中心 x；建议使用纵向应变。")
        else:
            raise ValueError("axis must be x or y")

        dx, dy, dist = roi_separation(self.roi1, self.roi2)
        self.log(f"对齐后距离：dx={dx:.3f}px, dy={dy:.3f}px, distance={dist:.3f}px")
        self.log_roi_texture("当前 ROI 1", self.roi1)
        self.log_roi_texture("当前 ROI 2", self.roi2)
        self.show_image()

    def make_group_from_current(self, name=None):
        if self.first_img8 is None:
            raise RuntimeError("请先加载第一张图。")
        if self.roi1 is None or self.roi2 is None:
            raise RuntimeError("请先画 ROI 1 和 ROI 2。")

        # 安全限制：ROI 必须在分析起始/参考帧上定义。
        start_1based = int(self.start_frame_1based.get())
        current_1based = int(self.current_preview_index + 1)
        if current_1based != start_1based:
            msg = (
                f"当前 ROI 是在第 {current_1based} 帧上画的，"
                f"但分析起始/参考帧是第 {start_1based} 帧。\n\n"
                f"为了保证模板和初始 ROI 一致，请先显示第 {start_1based} 帧再画 ROI，"
                f"或者点击“当前帧设为起始/参考”。"
            )
            raise RuntimeError(msg)

        selected = self.strain_mode.get()
        actual = resolve_strain_mode(self.roi1, self.roi2, selected)
        dx, dy, dist = roi_separation(self.roi1, self.roi2)
        L0 = length_between(self.roi1, self.roi2, actual)

        if name is None or not str(name).strip():
            name = f"G{self.next_group_idx:02d}"
            self.next_group_idx += 1

        name = safe_name(name)

        group = {
            "name": name,
            "roi1": tuple(self.roi1),
            "roi2": tuple(self.roi2),
            "selected_mode": selected,
            "actual_mode": actual,
            "dx0": dx,
            "dy0": dy,
            "dist0": dist,
            "L0": L0,
        }

        return group

    def check_group_warnings(self, group):
        messages = []

        if group["L0"] < 50:
            messages.append(
                f"L0 偏小：{group['L0']:.1f}px，线性应变误差会被放大。"
            )

        m1 = roi_texture_metrics(self.first_img8, group["roi1"])
        m2 = roi_texture_metrics(self.first_img8, group["roi2"])

        ok1 = texture_is_ok(
            m1,
            self.min_texture_std.get(),
            self.min_texture_contrast.get(),
            self.max_saturated_frac.get(),
        )
        ok2 = texture_is_ok(
            m2,
            self.min_texture_std.get(),
            self.min_texture_contrast.get(),
            self.max_saturated_frac.get(),
        )

        if not ok1:
            messages.append(
                f"ROI1 质量：偏弱，建议增大 ROI 或选择更独特散斑。std={m1['std_gray']:.1f}, P95-P5={m1['contrast_p95_p5']:.1f}。"
            )
        if not ok2:
            messages.append(
                f"ROI2 质量：偏弱，建议增大 ROI 或选择更独特散斑。std={m2['std_gray']:.1f}, P95-P5={m2['contrast_p95_p5']:.1f}。"
            )

        return messages

    def add_current_group(self):
        try:
            group = self.make_group_from_current(self.group_name_var.get())
        except Exception as exc:
            messagebox.showerror("无法添加 ROI 组", str(exc))
            return

        if any(g["name"] == group["name"] for g in self.roi_groups):
            messagebox.showerror("组名重复", f"已经存在组名：{group['name']}")
            return

        warnings = self.check_group_warnings(group)
        if warnings:
            text = "\n".join(warnings) + "\n\n是否仍然添加该组？"
            if not messagebox.askyesno("ROI 组警告", text):
                return

        self.roi_groups.append(group)
        self.refresh_group_tree()
        self.log_group_info("已添加", group)
        self.group_name_var.set("")
        self.show_image()

    def update_selected_group(self):
        selected_iid = self.get_selected_group_iid()
        if selected_iid is None:
            messagebox.showwarning("未选择组", "请先在列表中选择一组。")
            return

        try:
            new_group = self.make_group_from_current(self.roi_groups[selected_iid]["name"])
        except Exception as exc:
            messagebox.showerror("无法更新 ROI 组", str(exc))
            return

        warnings = self.check_group_warnings(new_group)
        if warnings:
            text = "\n".join(warnings) + "\n\n是否仍然更新该组？"
            if not messagebox.askyesno("ROI 组警告", text):
                return

        self.roi_groups[selected_iid] = new_group
        self.refresh_group_tree()
        self.log_group_info("已更新", new_group)
        self.show_image()

    def get_selected_group_iid(self):
        sel = self.group_tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def load_selected_group(self):
        idx = self.get_selected_group_iid()
        if idx is None:
            messagebox.showwarning("未选择组", "请先在列表中选择一组。")
            return
        if idx < 0 or idx >= len(self.roi_groups):
            return

        group = self.roi_groups[idx]
        self.roi1 = tuple(group["roi1"])
        self.roi2 = tuple(group["roi2"])
        self.strain_mode.set(group["selected_mode"])
        self.sync_strain_mode_display()
        self.group_name_var.set(group["name"])
        self.log_group_info("已载入", group)
        self.show_image()

    def delete_selected_group(self):
        idx = self.get_selected_group_iid()
        if idx is None:
            messagebox.showwarning("未选择组", "请先在列表中选择一组。")
            return
        if idx < 0 or idx >= len(self.roi_groups):
            return

        group = self.roi_groups[idx]
        if not messagebox.askyesno("删除 ROI 组", f"确定删除 {group['name']} 吗？"):
            return

        del self.roi_groups[idx]
        self.refresh_group_tree()
        self.log(f"已删除组：{group['name']}")
        self.show_image()

    def refresh_group_tree(self):
        self.group_tree.delete(*self.group_tree.get_children())
        for idx, g in enumerate(self.roi_groups):
            values = (
                g["name"],
                g["selected_mode"],
                g["actual_mode"],
                f"{g['L0']:.1f}",
                f"{g['dx0']:.1f}",
                f"{g['dy0']:.1f}",
                str(g["roi1"]),
                str(g["roi2"]),
            )
            self.group_tree.insert("", "end", iid=str(idx), values=values)

    def log_group_info(self, prefix, group):
        self.log(
            f"{prefix}组 {group['name']}: selected={group['selected_mode']}, "
            f"actual={group['actual_mode']}, L0={group['L0']:.3f}px, "
            f"dx={group['dx0']:.3f}px, dy={group['dy0']:.3f}px, "
            f"ROI1={group['roi1']}, ROI2={group['roi2']}"
        )

    def log_roi_texture(self, name, rect):
        if self.first_img8 is None or rect is None:
            return

        metrics = roi_texture_metrics(self.first_img8, rect)
        ok = texture_is_ok(
            metrics,
            self.min_texture_std.get(),
            self.min_texture_contrast.get(),
            self.max_saturated_frac.get(),
        )

        quality = "良好" if ok else "偏弱，建议增大 ROI 或选择更独特散斑"
        msg = (
            f"{name} 质量：{quality}。"
            f"std={metrics['std_gray']:.2f}, P95-P5={metrics['contrast_p95_p5']:.2f}, "
            f"low={metrics['low_frac']:.3f}, high={metrics['high_frac']:.3f}"
        )
        self.log(msg)

    # ---------- 处理前检查 ----------

    def validate_before_processing(self):
        if not self.image_paths:
            raise RuntimeError("请先加载第一张图。")
        if not self.roi_groups:
            raise RuntimeError("请先至少添加一组 ROI。")
        if not self.output_folder.get().strip():
            raise RuntimeError("请设置输出文件夹。")

        start_idx, end_idx = self.get_analysis_indices()
        if end_idx <= start_idx:
            raise RuntimeError("分析范围至少应包含两帧。")

        if self.search_radius.get() <= 0:
            raise RuntimeError("搜索半径必须 > 0。")
        if self.export_overlays.get() and self.overlay_every.get() <= 0:
            raise RuntimeError("overlay 保存间隔必须 > 0。")
        if not (-1 <= self.hard_corr.get() <= 1):
            raise RuntimeError("硬相关阈值应在 -1 到 1 之间。")
        if not (-1 <= self.soft_corr.get() <= 1):
            raise RuntimeError("软相关下限应在 -1 到 1 之间。")
        if self.soft_corr.get() > self.hard_corr.get():
            raise RuntimeError("软相关下限不能高于硬相关阈值。")
        if not (0 <= self.template_alpha.get() <= 1):
            raise RuntimeError("模板跟随系数应在 0 到 1 之间。")
        if self.fb_tolerance_px.get() <= 0:
            raise RuntimeError("FB 容差必须 > 0。")
        if not (0 <= self.max_saturated_frac.get() <= 1):
            raise RuntimeError("最大近黑/近白比例应在 0 到 1 之间。")

        if self.max_frame_strain_jump.get().strip():
            jump = float(self.max_frame_strain_jump.get().strip())
            if jump <= 0:
                raise RuntimeError("单帧应变突变上限必须 > 0，或者留空禁用。")

        if self.pixel_size_mm.get().strip():
            pix = float(self.pixel_size_mm.get().strip())
            if pix <= 0:
                raise RuntimeError("像素尺寸必须 > 0，或者留空。")

        very_small = [g for g in self.roi_groups if g["L0"] < 50]
        if very_small:
            names = ", ".join(g["name"] for g in very_small)
            msg = (
                f"以下 ROI 组的 L0 < 50 px：{names}\n\n"
                "这通常说明应变方向选错，或两个 ROI 太近。\n"
                "是否仍然继续？"
            )
            if not messagebox.askyesno("L0 过小警告", msg):
                raise RuntimeError("用户取消：某些 ROI 组 L0 太小。")

    # ---------- 批量处理 ----------

    def start_processing(self):
        if self.is_processing:
            messagebox.showinfo("正在处理", "程序正在处理，请等待当前任务完成。")
            return

        try:
            self.validate_before_processing()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.is_processing = True
        self.progress["value"] = 0

        thread = threading.Thread(target=self.process_images_thread, daemon=True)
        thread.start()

    def process_images_thread(self):
        try:
            self.process_images()
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("处理失败", str(exc)))
            self.root.after(0, lambda: self.log(traceback.format_exc()))
        finally:
            self.is_processing = False

    def init_group_states(self, first_img8):
        states = []

        for group in self.roi_groups:
            r1 = tuple(group["roi1"])
            r2 = tuple(group["roi2"])
            actual_mode = group["actual_mode"]
            L0 = length_between(r1, r2, actual_mode)

            state = {
                "group": group,
                "last_good_rect1": r1,
                "last_good_rect2": r2,
                "template1": extract_patch(first_img8, r1),
                "template2": extract_patch(first_img8, r2),
                "last_good_img8": first_img8.copy(),
                "L0": L0,
                "last_valid_strain": 0.0,
                "consecutive_fail_count": 0,
            }

            states.append(state)

        return states

    def process_one_group_one_frame(
        self,
        state,
        img8,
        frame_idx,
        filename,
        params,
    ):
        group = state["group"]
        group_name = group["name"]
        actual_mode = group["actual_mode"]

        search_radius_base = params["search_radius_base"]
        hard_corr = params["hard_corr"]
        soft_corr = params["soft_corr"]
        enable_adaptive = params["enable_adaptive"]
        use_prev_frame_template = params["use_prev_frame_template"]
        template_alpha = params["template_alpha"]
        max_frame_jump = params["max_frame_jump"]
        enable_fb_check = params["enable_fb_check"]
        fb_tolerance = params["fb_tolerance"]
        pixel_size_mm = params["pixel_size_mm"]

        last_good_rect1 = state["last_good_rect1"]
        last_good_rect2 = state["last_good_rect2"]
        template1 = state["template1"]
        template2 = state["template2"]
        last_good_img8 = state["last_good_img8"]
        L0 = state["L0"]
        last_valid_strain = state["last_valid_strain"]
        consecutive_fail_count = state["consecutive_fail_count"]

        candidate_rect1 = None
        candidate_rect2 = None
        score1 = 1.0
        score2 = 1.0
        fb_err1 = np.nan
        fb_err2 = np.nan
        fb_score1 = np.nan
        fb_score2 = np.nan

        if frame_idx == 0:
            accepted = True
            accept_mode = "initial"
            reason = "initial frame"
            L = L0
            strain = 0.0
            true_strain = 0.0
            used_rect1 = last_good_rect1
            used_rect2 = last_good_rect2
        else:
            radius_factor = min(5, 1 + consecutive_fail_count)
            search_radius = search_radius_base * radius_factor

            candidate_rect1, score1 = match_template_candidate(
                img8,
                last_good_rect1,
                template1,
                search_radius=search_radius,
            )
            candidate_rect2, score2 = match_template_candidate(
                img8,
                last_good_rect2,
                template2,
                search_radius=search_radius,
            )

            candidate_L = length_between(candidate_rect1, candidate_rect2, actual_mode)
            candidate_strain = (candidate_L - L0) / L0

            ok_jump = True
            jump_value = abs(candidate_strain - last_valid_strain)
            if max_frame_jump is not None:
                ok_jump = jump_value <= max_frame_jump

            ok_hard_corr = (score1 >= hard_corr) and (score2 >= hard_corr)
            ok_soft_corr = (score1 >= soft_corr) and (score2 >= soft_corr)

            ok_fb = True
            if enable_fb_check:
                fb_err1, fb_score1 = forward_backward_error(
                    last_good_img8,
                    img8,
                    last_good_rect1,
                    candidate_rect1,
                    search_radius=search_radius,
                )
                fb_err2, fb_score2 = forward_backward_error(
                    last_good_img8,
                    img8,
                    last_good_rect2,
                    candidate_rect2,
                    search_radius=search_radius,
                )
                ok_fb = (fb_err1 <= fb_tolerance) and (fb_err2 <= fb_tolerance)

            if ok_hard_corr and ok_jump:
                accepted = True
                accept_mode = "hard"
                reason = "hard corr + continuous strain"
            elif enable_adaptive and ok_soft_corr and ok_jump and ok_fb:
                accepted = True
                accept_mode = "adaptive"
                reason = "soft corr + continuous strain + FB check"
            else:
                accepted = False
                accept_mode = "rejected"

                fail_reasons = []
                if not ok_hard_corr:
                    fail_reasons.append(
                        f"hard corr fail: ROI1 {score1:.3f}, ROI2 {score2:.3f} < {hard_corr:.3f}"
                    )
                if enable_adaptive and not ok_soft_corr:
                    fail_reasons.append(
                        f"soft corr fail: ROI1 {score1:.3f}, ROI2 {score2:.3f} < {soft_corr:.3f}"
                    )
                if not ok_jump:
                    if max_frame_jump is not None:
                        fail_reasons.append(
                            f"strain jump {jump_value:.4f} > {max_frame_jump:.4f}"
                        )
                    else:
                        fail_reasons.append("strain jump check disabled but failed unexpectedly")
                if enable_fb_check and not ok_fb:
                    fail_reasons.append(
                        f"FB fail: ROI1 {fb_err1:.2f}px, ROI2 {fb_err2:.2f}px > {fb_tolerance:.2f}px"
                    )

                reason = "; ".join(fail_reasons) if fail_reasons else "rejected"

            if accepted:
                used_rect1 = candidate_rect1
                used_rect2 = candidate_rect2

                L = candidate_L
                strain = candidate_strain
                true_strain = math.log(L / L0) if L > 0 else np.nan

                state["last_good_rect1"] = used_rect1
                state["last_good_rect2"] = used_rect2
                state["last_valid_strain"] = strain
                state["consecutive_fail_count"] = 0

                if use_prev_frame_template:
                    state["template1"] = update_template_from_rect(img8, used_rect1, template1, template_alpha)
                    state["template2"] = update_template_from_rect(img8, used_rect2, template2, template_alpha)

                state["last_good_img8"] = img8.copy()
            else:
                used_rect1 = last_good_rect1
                used_rect2 = last_good_rect2

                L = np.nan
                strain = np.nan
                true_strain = np.nan

                state["consecutive_fail_count"] = consecutive_fail_count + 1

        c1x, c1y = rect_center(used_rect1)
        c2x, c2y = rect_center(used_rect2)

        row = {
            "frame": frame_idx,
            "filename": filename,
            "group": group_name,
            "selected_mode": group["selected_mode"],
            "actual_mode": actual_mode,
            "accepted": accepted,
            "accept_mode": accept_mode,
            "reason": reason,
            "consecutive_fail_count": state["consecutive_fail_count"],
            "corr_score_roi1": score1,
            "corr_score_roi2": score2,
            "fb_error_roi1_px": fb_err1,
            "fb_error_roi2_px": fb_err2,
            "fb_score_roi1": fb_score1,
            "fb_score_roi2": fb_score2,
            "L0_px": L0,
            "used_roi1_x_px": used_rect1[0],
            "used_roi1_y_px": used_rect1[1],
            "used_roi1_w_px": used_rect1[2],
            "used_roi1_h_px": used_rect1[3],
            "used_roi1_center_x_px": c1x,
            "used_roi1_center_y_px": c1y,
            "used_roi2_x_px": used_rect2[0],
            "used_roi2_y_px": used_rect2[1],
            "used_roi2_w_px": used_rect2[2],
            "used_roi2_h_px": used_rect2[3],
            "used_roi2_center_x_px": c2x,
            "used_roi2_center_y_px": c2y,
            "length_px": L,
            "engineering_strain": strain,
            "true_strain": true_strain,
            "last_valid_engineering_strain": state["last_valid_strain"],
        }

        if candidate_rect1 is not None:
            cc1x, cc1y = rect_center(candidate_rect1)
            row["candidate_roi1_center_x_px"] = cc1x
            row["candidate_roi1_center_y_px"] = cc1y
        else:
            row["candidate_roi1_center_x_px"] = np.nan
            row["candidate_roi1_center_y_px"] = np.nan

        if candidate_rect2 is not None:
            cc2x, cc2y = rect_center(candidate_rect2)
            row["candidate_roi2_center_x_px"] = cc2x
            row["candidate_roi2_center_y_px"] = cc2y
        else:
            row["candidate_roi2_center_x_px"] = np.nan
            row["candidate_roi2_center_y_px"] = np.nan

        if pixel_size_mm is not None and np.isfinite(L):
            row["length_mm"] = L * pixel_size_mm
            row["elongation_mm"] = (L - L0) * pixel_size_mm

        overlay_info = {
            "used_rect1": used_rect1,
            "used_rect2": used_rect2,
            "candidate_rect1": candidate_rect1,
            "candidate_rect2": candidate_rect2,
            "strain": strain,
            "last_valid_strain": state["last_valid_strain"],
            "score1": score1,
            "score2": score2,
            "accepted": accepted,
            "accept_mode": accept_mode,
            "reason": reason,
            "fb_err1": fb_err1,
            "fb_err2": fb_err2,
        }

        return row, overlay_info

    def process_images(self):
        output_dir = Path(self.output_folder.get().strip())
        output_dir.mkdir(parents=True, exist_ok=True)
        core_dir = output_dir / "core"
        qc_dir = output_dir / "qc"
        optional_dir = output_dir / "optional"

        start_idx, end_idx = self.get_analysis_indices()
        image_paths_run = self.image_paths[start_idx:end_idx + 1]

        search_radius_base = int(self.search_radius.get())
        hard_corr = float(self.hard_corr.get())
        soft_corr = float(self.soft_corr.get())

        enable_adaptive = bool(self.enable_adaptive.get())
        use_prev_frame_template = bool(self.use_prev_frame_template.get())
        template_alpha = float(self.template_alpha.get())

        enable_fb_check = bool(self.enable_fb_check.get())
        fb_tolerance = float(self.fb_tolerance_px.get())

        overlay_every = int(self.overlay_every.get())

        max_frame_jump = None
        if self.max_frame_strain_jump.get().strip():
            max_frame_jump = float(self.max_frame_strain_jump.get().strip())

        pixel_size_mm = None
        if self.pixel_size_mm.get().strip():
            pixel_size_mm = float(self.pixel_size_mm.get().strip())

        export_origin_txt = bool(self.export_origin_txt.get())
        export_engineering_png = bool(self.export_engineering_png.get())
        export_qc_summary = bool(self.export_qc_summary.get())
        export_full_csv = bool(self.export_full_csv.get())
        export_corr_plot = bool(self.export_corr_plot.get())
        export_overlays = bool(self.export_overlays.get())
        export_parameters = bool(self.export_parameters.get())

        params = {
            "search_radius_base": search_radius_base,
            "hard_corr": hard_corr,
            "soft_corr": soft_corr,
            "enable_adaptive": enable_adaptive,
            "use_prev_frame_template": use_prev_frame_template,
            "template_alpha": template_alpha,
            "max_frame_jump": max_frame_jump,
            "enable_fb_check": enable_fb_check,
            "fb_tolerance": fb_tolerance,
            "pixel_size_mm": pixel_size_mm,
        }

        first_raw = read_gray_image(image_paths_run[0])
        first_img8 = normalize_to_uint8(first_raw)

        states = self.init_group_states(first_img8)

        overlay_dirs = {}
        if export_overlays:
            overlay_root = optional_dir / "overlays"
            for state in states:
                gname = safe_name(state["group"]["name"])
                gdir = overlay_root / gname
                gdir.mkdir(parents=True, exist_ok=True)
                overlay_dirs[state["group"]["name"]] = gdir

        all_rows = []
        n = len(image_paths_run)
        total_work = n * len(states)
        done_work = 0

        self.root.after(0, lambda: self.log(
            f"开始处理，分析范围：第 {start_idx + 1} 到第 {end_idx + 1} 帧，"
            f"共 {n} 张图，{len(states)} 组 ROI。"
        ))
        self.root.after(0, lambda: self.status_var.set("正在批量追踪多组 ROI 并计算应变..."))

        for i, path in enumerate(image_paths_run):
            raw = read_gray_image(path)
            img8 = normalize_to_uint8(raw)
            fname = os.path.basename(path)

            for state in states:
                row, overlay_info = self.process_one_group_one_frame(
                    state=state,
                    img8=img8,
                    frame_idx=i,
                    filename=fname,
                    params=params,
                )
                row["frame_local_1based"] = i + 1
                row["frame_global_1based"] = start_idx + i + 1
                all_rows.append(row)

                group = state["group"]
                group_name = group["name"]
                actual_mode = group["actual_mode"]

                accepted = overlay_info["accepted"]
                accept_mode = overlay_info["accept_mode"]

                save_overlay = export_overlays and (
                    i % overlay_every == 0 or i == n - 1 or not accepted or accept_mode == "adaptive"
                )
                if save_overlay:
                    overlay = draw_group_overlay(
                        img8,
                        group_name,
                        actual_mode,
                        overlay_info["used_rect1"],
                        overlay_info["used_rect2"],
                        overlay_info["candidate_rect1"],
                        overlay_info["candidate_rect2"],
                        i,
                        overlay_info["strain"],
                        overlay_info["last_valid_strain"],
                        overlay_info["score1"],
                        overlay_info["score2"],
                        accepted,
                        accept_mode,
                        overlay_info["reason"],
                        fb_err1=overlay_info["fb_err1"] if np.isfinite(overlay_info["fb_err1"]) else None,
                        fb_err2=overlay_info["fb_err2"] if np.isfinite(overlay_info["fb_err2"]) else None,
                    )
                    out_name = overlay_dirs[group_name] / f"tracked_{i:05d}.png"
                    cv2.imwrite(str(out_name), overlay)

                done_work += 1
                if done_work % max(1, len(states) * 5) == 0 or not accepted or accept_mode == "adaptive" or i == n - 1:
                    progress_val = done_work / total_work * 100
                    strain_text = f"{overlay_info['strain']:.6f}" if np.isfinite(overlay_info["strain"]) else "NaN"
                    msg = (
                        f"Frame {i+1}/{n}, Group {group_name}: {accept_mode}, "
                        f"strain={strain_text}, corr=({overlay_info['score1']:.3f}, {overlay_info['score2']:.3f})"
                    )
                    self.root.after(0, lambda v=progress_val: self.progress.config(value=v))
                    self.root.after(0, lambda m=msg: self.status_var.set(m))
                    self.root.after(0, lambda m=msg: self.log(m))

        df = pd.DataFrame(all_rows)
        summary = build_qc_summary(df)
        written_paths = []

        if export_origin_txt or export_engineering_png:
            core_dir.mkdir(parents=True, exist_ok=True)

        for group in self.roi_groups:
            gname = group["name"]
            sg = safe_name(gname)
            gdf = df[df["group"] == gname].copy()

            if export_origin_txt:
                txt_path = core_dir / f"strain_{sg}.txt"
                write_origin_txt(gdf, txt_path)
                written_paths.append(txt_path)

            if export_engineering_png:
                fig_path = core_dir / f"engineering_strain_{sg}.png"
                plot_engineering_strain(gdf, fig_path, f"Engineering strain - {gname}")
                written_paths.append(fig_path)

        if export_origin_txt:
            all_txt = core_dir / "strain_all_groups.txt"
            write_all_groups_origin_txt(df, all_txt)
            written_paths.append(all_txt)

        if export_engineering_png:
            combined_fig = core_dir / "engineering_strain_all_groups.png"
            plt.figure(figsize=(8, 5))
            for group in self.roi_groups:
                gname = group["name"]
                gdf = df[df["group"] == gname]
                plt.plot(gdf["frame_global_1based"], gdf["engineering_strain"], linewidth=1, label=gname)
            plt.xlabel("Frame")
            plt.ylabel("Engineering strain")
            plt.title("Engineering strain - all ROI groups")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            plt.savefig(combined_fig, dpi=300)
            plt.close()
            written_paths.append(combined_fig)

        if export_qc_summary:
            qc_path = qc_dir / "qc_summary.txt"
            write_qc_summary(summary, qc_path)
            written_paths.append(qc_path)

        if export_full_csv:
            full_csv_dir = optional_dir / "full_csv"
            full_csv_dir.mkdir(parents=True, exist_ok=True)
            all_csv = full_csv_dir / "strain_results_all_groups.csv"
            df.to_csv(all_csv, index=False, encoding="utf-8-sig")
            written_paths.append(all_csv)

            group_dir = full_csv_dir / "per_group_results"
            group_dir.mkdir(parents=True, exist_ok=True)
            for group in self.roi_groups:
                gname = group["name"]
                sg = safe_name(gname)
                gdf = df[df["group"] == gname].copy()
                g_csv = group_dir / f"strain_results_{sg}.csv"
                gdf.to_csv(g_csv, index=False, encoding="utf-8-sig")
                written_paths.append(g_csv)

        if export_corr_plot:
            corr_dir = optional_dir / "correlation_plots"
            corr_dir.mkdir(parents=True, exist_ok=True)
            for group in self.roi_groups:
                gname = group["name"]
                sg = safe_name(gname)
                gdf = df[df["group"] == gname].copy()
                corr_path = corr_dir / f"correlation_scores_{sg}.png"
                plt.figure(figsize=(7, 5))
                plt.plot(gdf["frame_global_1based"], gdf["corr_score_roi1"], marker="o", markersize=3, linewidth=1, label="ROI 1")
                plt.plot(gdf["frame_global_1based"], gdf["corr_score_roi2"], marker="s", markersize=3, linewidth=1, label="ROI 2")
                plt.axhline(hard_corr, linestyle="--", linewidth=1, label="strict threshold")
                plt.axhline(soft_corr, linestyle=":", linewidth=1, label="weak threshold")
                plt.xlabel("Frame")
                plt.ylabel("Normalized correlation score")
                plt.title(f"Correlation scores - {gname}")
                plt.grid(True)
                plt.legend()
                plt.tight_layout()
                plt.savefig(corr_path, dpi=300)
                plt.close()
                written_paths.append(corr_path)

        if export_parameters:
            param_dir = optional_dir / "parameters"
            param_dir.mkdir(parents=True, exist_ok=True)
            params_path = param_dir / "tracking_parameters.txt"
            with open(params_path, "w", encoding="utf-8") as f:
                f.write("DIC Virtual Extensometer GUI v7 Multi-ROI Range Preview Parameters\n")
                f.write("----------------------------------------------------\n")
                f.write(f"image_folder = {self.image_folder.get()}\n")
                f.write(f"number_of_images_in_analysis_range = {n}\n")
                f.write(f"start_frame_1based = {start_idx + 1}\n")
                f.write(f"end_frame_1based = {end_idx + 1}\n")
                f.write(f"number_of_groups = {len(self.roi_groups)}\n")
                f.write(f"tracking_preset = {self.tracking_preset.get()}\n")
                f.write(f"search_radius_base_px = {search_radius_base}\n")
                f.write(f"hard_corr = {hard_corr}\n")
                f.write(f"soft_corr = {soft_corr}\n")
                f.write(f"enable_adaptive = {enable_adaptive}\n")
                f.write(f"use_prev_frame_template = {use_prev_frame_template}\n")
                f.write(f"template_alpha = {template_alpha}\n")
                f.write(f"max_frame_strain_jump = {max_frame_jump}\n")
                f.write(f"enable_fb_check = {enable_fb_check}\n")
                f.write(f"fb_tolerance_px = {fb_tolerance}\n")
                f.write(f"pixel_size_mm = {pixel_size_mm}\n")
                f.write(f"overlay_every = {overlay_every}\n")
                f.write("\nGroups:\n")
                for g in self.roi_groups:
                    f.write(
                        f"{g['name']}: selected={g['selected_mode']}, actual={g['actual_mode']}, "
                        f"L0={g['L0']:.6f}px, dx={g['dx0']:.6f}px, dy={g['dy0']:.6f}px, "
                        f"roi1={g['roi1']}, roi2={g['roi2']}\n"
                    )
            written_paths.append(params_path)

            acceptance_path = param_dir / "acceptance_summary.txt"
            with open(acceptance_path, "w", encoding="utf-8") as f:
                f.write("Acceptance summary by group\n")
                f.write("---------------------------\n")
                for gname, sub in df.groupby("group"):
                    f.write(f"\n[{gname}]\n")
                    f.write(str(sub["accept_mode"].value_counts(dropna=False)))
                    f.write("\nRejected frames:\n")
                    rejected = sub[sub["accepted"] == False]
                    if len(rejected) == 0:
                        f.write("None\n")
                    else:
                        f.write(rejected[["frame_global_1based", "filename", "reason"]].to_string(index=False))
                        f.write("\n")
            written_paths.append(acceptance_path)

        n_rejected = summary["overall"]["rejected_frames"]
        n_adaptive = summary["overall"]["adaptive_accepted_frames"]
        qc_level = summary["overall"]["qc_level"]

        path_log = "输出文件：\n" + "\n".join(str(p) for p in written_paths)
        done_msg = (
            f"处理完成。\n"
            f"核心结果已保存到: {core_dir if (export_origin_txt or export_engineering_png) else output_dir}\n"
            f"QC 状态: {qc_level}\n"
            f"Rejected frames: {n_rejected}\n"
            f"Adaptive accepted frames: {n_adaptive}"
        )

        self.root.after(0, lambda: self.progress.config(value=100))
        self.root.after(0, lambda: self.status_var.set(f"处理完成，QC 状态：{qc_level}"))
        self.root.after(0, lambda: self.log(done_msg + "\n" + path_log))
        self.root.after(0, lambda: messagebox.showinfo("完成", done_msg))

    def run(self):
        self.root.mainloop()


def main():
    root = tk.Tk()
    app = MultiROIGUI(root)
    app.run()


if __name__ == "__main__":
    main()
