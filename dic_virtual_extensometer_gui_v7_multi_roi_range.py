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
import queue
import threading
import traceback
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")

# 科研人员中文 Windows 环境字体支持（解决 matplotlib 图中中文乱码/方框）
# 优先使用系统中常见的微软雅黑 / 黑体，失败时回退到 DejaVu Sans
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "Arial Unicode MS",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk


APP_NAME = "ezDIC"
APP_VERSION = "0.1.3"
APP_DEVELOPER = "Dr. Delun Gong"
APP_DOI = "10.5281/zenodo.20222465"
APP_DOI_URL = f"https://doi.org/{APP_DOI}"
APP_TITLE = f"{APP_NAME} v{APP_VERSION} - Developed by {APP_DEVELOPER} - DOI: {APP_DOI}"
ORIGIN_OPJU_FILENAME = "ezDIC_results.opju"

CITATION_TEXT = f"""Recommended citation:

Gong, D. (2026). ezDIC: A lightweight virtual extensometer for extracting linear strain from image sequences (Version {APP_VERSION}) [Computer software]. Zenodo. {APP_DOI_URL}
"""

USAGE_NOTICE = f"""ezDIC Attribution and Usage Notice

Developer:
{APP_DEVELOPER}

DOI:
{APP_DOI}

This software was developed by {APP_DEVELOPER} for lightweight extraction of linear strain from image sequences.

{CITATION_TEXT.strip()}

Users are not permitted to:
1. claim that they developed this software;
2. remove or alter the developer attribution;
3. redistribute, copy, forward, or share this software with unauthorized users;
4. use this software outside the authorized research or teaching context.

If you use ezDIC in a thesis, paper, presentation, or report, please cite the DOI above.

If you need to share or reuse this software, please obtain permission from {APP_DEVELOPER} first.
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

ROI_ROLE_LABEL_TO_VALUE = {
    "普通": "none",
    "拉伸方向": "axial",
    "横向方向": "transverse",
}
ROI_ROLE_VALUE_TO_LABEL = {v: k for k, v in ROI_ROLE_LABEL_TO_VALUE.items()}
ROI_ROLE_VALUES = set(ROI_ROLE_VALUE_TO_LABEL)
POISSON_MIN_ABS_AXIAL_ENGINEERING_STRAIN = 1e-6


def open_output_folder(path):
    folder = Path(path)
    if not folder.exists():
        raise RuntimeError(f"结果目录不存在：{folder}")
    if not folder.is_dir():
        raise RuntimeError(f"结果路径不是文件夹：{folder}")
    if not hasattr(os, "startfile"):
        raise RuntimeError("自动打开结果目录仅支持 Windows Explorer。")
    os.startfile(str(folder))


class ToolTip:
    def __init__(self, widget, text, wraplength=360, delay_ms=450):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.delay_ms = delay_ms
        self.after_id = None
        self.tip_window = None

        self.widget._tooltip_text = text
        self.widget.bind("<Enter>", self.schedule, add="+")
        self.widget.bind("<Leave>", self.hide, add="+")
        self.widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, event=None):
        self.unschedule()
        self.after_id = self.widget.after(self.delay_ms, self.show)

    def unschedule(self):
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None

    def show(self):
        self.after_id = None
        if self.tip_window is not None or not self.text:
            return

        try:
            wx = self.widget.winfo_rootx()
            wy = self.widget.winfo_rooty()
            ww = self.widget.winfo_width()
            wh = self.widget.winfo_height()
            screen_w = self.widget.winfo_screenwidth()
            screen_h = self.widget.winfo_screenheight()

            x = wx + 18
            y = wy + wh + 8

            # 防止提示跑到屏幕外（右下角裁切是科研笔记本常见问题）
            est_width = min(self.wraplength + 40, 520)
            est_height = 120   # 粗略估计多行提示高度

            if x + est_width > screen_w - 20:
                x = max(20, screen_w - est_width - 20)
            if y + est_height > screen_h - 40:
                y = max(20, wy - est_height - 10)   # 放上面
        except tk.TclError:
            return

        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(
            self.tip_window,
            text=self.text,
            justify=tk.LEFT,
            wraplength=self.wraplength,
            background="#fff8dc",
            relief=tk.SOLID,
            borderwidth=1,
            padding=(8, 5),
        )
        label.pack()

    def hide(self, event=None):
        self.unschedule()
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


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


def _engineering_to_true(value):
    if pd.isna(value) or not np.isfinite(float(value)) or (1.0 + float(value)) <= 0:
        return np.nan
    return math.log1p(float(value))


def _format_origin_value(column, value):
    if column.startswith("ValidGroupCount_"):
        return "NaN" if pd.isna(value) else str(int(value))
    return _format_origin_float(value)


def normalize_roi_role(role):
    role = str(role or "none").strip()
    if role not in ROI_ROLE_VALUES:
        return "none"
    return role


def poisson_roles_are_configured(groups):
    return any(normalize_roi_role(g.get("role", "none")) != "none" for g in groups)


def get_poisson_role_groups(groups):
    axial = [g for g in groups if normalize_roi_role(g.get("role", "none")) == "axial"]
    transverse = [g for g in groups if normalize_roi_role(g.get("role", "none")) == "transverse"]
    return axial, transverse


def _validate_single_actual_mode(groups, role_label):
    modes = sorted({str(g.get("actual_mode", "unknown") or "unknown").strip() for g in groups})
    if len(modes) > 1:
        raise RuntimeError(f"{role_label} ROI 组的 actual_mode 必须一致；当前为 {', '.join(modes)}。")


def validate_poisson_role_groups(groups):
    if not poisson_roles_are_configured(groups):
        return False

    axial, transverse = get_poisson_role_groups(groups)
    errors = []
    if len(axial) < 1:
        errors.append(f"拉伸方向 ROI 组必须至少有 1 个；当前为 {len(axial)} 个。")
    if len(transverse) < 1:
        errors.append(f"横向方向 ROI 组必须至少有 1 个；当前为 {len(transverse)} 个。")
    if errors:
        raise RuntimeError("\n".join(errors))
    axial_names = {g.get("name") for g in axial}
    transverse_names = {g.get("name") for g in transverse}
    if axial_names & transverse_names:
        raise RuntimeError("同一个 ROI 组不能同时作为拉伸方向和横向方向。")
    _validate_single_actual_mode(axial, "拉伸方向")
    _validate_single_actual_mode(transverse, "横向方向")
    return True


def build_core_strain_table(gdf):
    """
    Build the minimal Origin-friendly strain table:
    Frame, EngineeringStrain, TrueStrain.
    True strain is recomputed from engineering strain to keep export logic explicit.
    """
    frame_col = _frame_column(gdf)
    frames = pd.to_numeric(gdf[frame_col], errors="coerce")
    eng = pd.to_numeric(gdf["engineering_strain"], errors="coerce")

    true_values = [_engineering_to_true(value) for value in eng]

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


def _group_engineering_strain_table(df, group_name, output_column):
    gdf = df[df["group"] == group_name].copy()
    if gdf.empty:
        return pd.DataFrame(columns=["Frame", output_column])

    table = build_core_strain_table(gdf)
    strain = table["EngineeringStrain"].astype(float)
    if "accepted" in gdf.columns:
        accepted = gdf["accepted"].astype(bool).reset_index(drop=True)
        strain = strain.where(accepted, np.nan)

    return pd.DataFrame(
        {
            "Frame": table["Frame"],
            output_column: strain,
        }
    ).reset_index(drop=True)


def _frame_table(df):
    frame_col = _frame_column(df)
    frames = pd.to_numeric(df[frame_col], errors="coerce").dropna().drop_duplicates().sort_values()
    return pd.DataFrame({"Frame": frames.astype("Int64")}).reset_index(drop=True)


def _mean_group_key(group):
    role = normalize_roi_role(group.get("role", "none"))
    actual_mode = str(group.get("actual_mode", "unknown") or "unknown").strip()
    return safe_name(f"{role}_{actual_mode}")


def _mean_group_specs(groups):
    specs = {}
    for group in groups or []:
        key = _mean_group_key(group)
        if key not in specs:
            specs[key] = {"key": key, "groups": []}
        specs[key]["groups"].append(group)
    return list(specs.values())


def _mean_engineering_strain_table_for_groups(df, groups, output_column):
    out = _frame_table(df)
    if out.empty:
        return pd.DataFrame(columns=["Frame", output_column])

    strain_cols = []
    merged = out.copy()
    for idx, group in enumerate(groups, start=1):
        col = f"__strain_{idx}"
        group_table = _group_engineering_strain_table(df, group.get("name"), col)
        merged = pd.merge(merged, group_table, on="Frame", how="left")
        strain_cols.append(col)

    if not strain_cols:
        merged[output_column] = np.nan
    else:
        strains = merged[strain_cols].apply(pd.to_numeric, errors="coerce")
        counts = strains.notna().sum(axis=1)
        merged[output_column] = strains.mean(axis=1, skipna=True).where(counts > 0, np.nan)

    return merged[["Frame", output_column]].reset_index(drop=True)


def build_mean_strain_table(df, groups):
    out = _frame_table(df)
    if out.empty or not groups:
        return out

    for spec in _mean_group_specs(groups):
        key = spec["key"]
        merged = out.copy()
        strain_cols = []
        for idx, group in enumerate(spec["groups"], start=1):
            col = f"__{key}_{idx}"
            group_table = _group_engineering_strain_table(df, group.get("name"), col)
            merged = pd.merge(merged, group_table, on="Frame", how="left")
            strain_cols.append(col)

        strains = merged[strain_cols].apply(pd.to_numeric, errors="coerce")
        counts = strains.notna().sum(axis=1)
        mean = strains.mean(axis=1, skipna=True).where(counts > 0, np.nan)
        std = strains.std(axis=1, skipna=True, ddof=1).where(counts >= 2, np.nan)
        sem = (std / np.sqrt(counts.astype(float))).where(counts >= 2, np.nan)

        out[f"MeanEngineeringStrain_{key}"] = mean
        out[f"MeanTrueStrain_{key}"] = mean.apply(_engineering_to_true)
        out[f"StdEngineeringStrain_{key}"] = std
        out[f"SemEngineeringStrain_{key}"] = sem
        out[f"ValidGroupCount_{key}"] = counts.astype(int)

    return out.reset_index(drop=True)


def build_poisson_ratio_table(df, groups, min_abs_axial=POISSON_MIN_ABS_AXIAL_ENGINEERING_STRAIN):
    if not validate_poisson_role_groups(groups):
        raise RuntimeError("请先设置 1 个拉伸方向 ROI 组和 1 个横向方向 ROI 组。")
    axial_groups, transverse_groups = get_poisson_role_groups(groups)

    axial = _mean_engineering_strain_table_for_groups(df, axial_groups, "AxialEngineeringStrain")
    transverse = _mean_engineering_strain_table_for_groups(df, transverse_groups, "TransverseEngineeringStrain")
    merged = pd.merge(axial, transverse, on="Frame", how="outer").sort_values("Frame").reset_index(drop=True)

    axial_strain = pd.to_numeric(merged["AxialEngineeringStrain"], errors="coerce").astype(float)
    transverse_strain = pd.to_numeric(merged["TransverseEngineeringStrain"], errors="coerce").astype(float)
    valid = (
        axial_strain.notna()
        & transverse_strain.notna()
        & np.isfinite(axial_strain)
        & np.isfinite(transverse_strain)
        & (axial_strain.abs() >= float(min_abs_axial))
    )
    poisson = pd.Series(np.nan, index=merged.index, dtype=float)
    poisson.loc[valid] = -transverse_strain.loc[valid] / axial_strain.loc[valid]
    merged["PoissonRatio"] = poisson

    return merged[
        ["Frame", "AxialEngineeringStrain", "TransverseEngineeringStrain", "PoissonRatio"]
    ].reset_index(drop=True)


def build_all_groups_strain_table(df, groups=None):
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
    merged = merged.sort_values("Frame").reset_index(drop=True)

    if groups is not None:
        mean_table = build_mean_strain_table(df, groups)
        if len(mean_table.columns) > 1:
            merged = pd.merge(merged, mean_table, on="Frame", how="outer")
            merged = merged.sort_values("Frame").reset_index(drop=True)

    if groups is not None and poisson_roles_are_configured(groups):
        poisson = build_poisson_ratio_table(df, groups)
        merged = pd.merge(merged, poisson, on="Frame", how="outer")
        merged = merged.sort_values("Frame").reset_index(drop=True)

    return merged


def write_all_groups_origin_txt(df, path, groups=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = build_all_groups_strain_table(df, groups)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(table.columns) + "\n")
        for _, row in table.iterrows():
            values = []
            for col in table.columns:
                if col == "Frame":
                    values.append("NaN" if pd.isna(row[col]) else str(int(row[col])))
                else:
                    values.append(_format_origin_value(col, row[col]))
            f.write("\t".join(values) + "\n")


def write_mean_groups_origin_txt(df, groups, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = build_mean_strain_table(df, groups)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(table.columns) + "\n")
        for _, row in table.iterrows():
            values = []
            for col in table.columns:
                if col == "Frame":
                    values.append("NaN" if pd.isna(row[col]) else str(int(row[col])))
                else:
                    values.append(_format_origin_value(col, row[col]))
            f.write("\t".join(values) + "\n")


def write_poisson_ratio_txt(df, groups, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = build_poisson_ratio_table(df, groups)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("Frame\tAxialEngineeringStrain\tTransverseEngineeringStrain\tPoissonRatio\n")
        for _, row in table.iterrows():
            frame = "NaN" if pd.isna(row["Frame"]) else str(int(row["Frame"]))
            f.write(
                f"{frame}\t"
                f"{_format_origin_float(row['AxialEngineeringStrain'])}\t"
                f"{_format_origin_float(row['TransverseEngineeringStrain'])}\t"
                f"{_format_origin_float(row['PoissonRatio'])}\n"
            )


def build_origin_project_tables(df, groups):
    groups = list(groups or [])
    tables = []

    for group in groups:
        gname = group.get("name")
        sg = safe_name(gname)
        gdf = df[df["group"] == gname].copy()
        tables.append((f"strain_{sg}", build_core_strain_table(gdf)))

    tables.append(("strain_all_groups", build_all_groups_strain_table(df, groups)))

    mean_table = build_mean_strain_table(df, groups)
    if len(mean_table.columns) > 1:
        tables.append(("strain_mean_groups", mean_table))

    if poisson_roles_are_configured(groups):
        tables.append(("poisson_ratio", build_poisson_ratio_table(df, groups)))

    return tables


def _load_originpro_module():
    try:
        import originpro as op
    except ImportError as exc:
        raise RuntimeError(
            "无法导入 originpro。请在 Windows + OriginPro 2021+ 环境中安装 originpro Python 包后再导出 OPJU。"
        ) from exc
    return op


def write_origin_opju_project(df, groups, path, origin_module=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    op = origin_module if origin_module is not None else _load_originpro_module()

    try:
        op.new(asksave=True)
        for table_name, table in build_origin_project_tables(df, groups):
            worksheet = op.new_sheet("w", lname=table_name)
            if worksheet is None:
                raise RuntimeError(f"无法创建 Origin worksheet：{table_name}")
            worksheet.from_df(table)

        if not op.save(str(path)):
            raise RuntimeError(f"保存 Origin OPJU 项目失败：{path}")
    except RuntimeError as exc:
        message = str(exc)
        if message.startswith("保存 Origin OPJU 项目失败") or message.startswith("无法"):
            raise
        raise RuntimeError(f"生成 Origin OPJU 项目失败：{exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"生成 Origin OPJU 项目失败：{exc}") from exc

    return path


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


def plot_all_groups_engineering_strain(df, groups, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(8, 5))
    for group in groups:
        gname = group["name"]
        gdf = df[df["group"] == gname]
        if gdf.empty:
            continue
        plt.plot(gdf["frame_global_1based"], gdf["engineering_strain"], linewidth=1, alpha=0.55, label=gname)

    mean_table = build_mean_strain_table(df, groups)
    if not mean_table.empty:
        frame = mean_table["Frame"].astype(float)
        for col in [c for c in mean_table.columns if c.startswith("MeanEngineeringStrain_")]:
            key = col.replace("MeanEngineeringStrain_", "", 1)
            mean = pd.to_numeric(mean_table[col], errors="coerce").astype(float)
            std_col = f"StdEngineeringStrain_{key}"
            plt.plot(frame, mean, linewidth=2.4, label=f"Mean {key}")
            if std_col in mean_table.columns:
                std = pd.to_numeric(mean_table[std_col], errors="coerce").astype(float)
                finite = mean.notna() & std.notna() & np.isfinite(mean) & np.isfinite(std)
                if finite.any():
                    plt.fill_between(frame[finite], mean[finite] - std[finite], mean[finite] + std[finite], alpha=0.12)

    plt.xlabel("Frame")
    plt.ylabel("Engineering strain")
    plt.title("Engineering strain - all ROI groups")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()


def plot_poisson_ratio(df, groups, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    table = build_poisson_ratio_table(df, groups)
    frame = table["Frame"].astype(float)
    ratio = table["PoissonRatio"].astype(float)
    valid = ratio.notna() & np.isfinite(ratio)

    plt.figure(figsize=(7, 5))
    plt.plot(frame, ratio, color="#2ca02c", linewidth=1, alpha=0.7)
    if valid.any():
        plt.scatter(frame[valid], ratio[valid], color="#2ca02c", s=18, label="Valid")
    invalid = ~valid
    if invalid.any():
        finite_ratio = ratio[valid]
        if len(finite_ratio) > 0:
            ymin = float(finite_ratio.min())
            ymax = float(finite_ratio.max())
            span = max(ymax - ymin, 1e-6)
            invalid_y = np.full(int(invalid.sum()), ymin - 0.08 * span)
        else:
            invalid_y = np.zeros(int(invalid.sum()))
        plt.scatter(frame[invalid], invalid_y, color="#d62728", marker="x", s=38, label="NaN")

    plt.xlabel("Frame")
    plt.ylabel("Poisson ratio")
    plt.title("Poisson ratio")
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
        self.configure_initial_window()

        self.image_folder = tk.StringVar()
        self.output_folder = tk.StringVar()

        self.search_radius = tk.IntVar(value=180)
        self.hard_corr = tk.DoubleVar(value=0.55)
        self.soft_corr = tk.DoubleVar(value=0.35)
        self.strain_mode = tk.StringVar(value="auto")
        self.strain_mode_display = tk.StringVar(value=STRAIN_MODE_VALUE_TO_LABEL["auto"])
        self.roi_role = tk.StringVar(value="none")
        self.roi_role_display = tk.StringVar(value=ROI_ROLE_VALUE_TO_LABEL["none"])
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
        self.export_origin_opju = tk.BooleanVar(value=False)
        self.export_engineering_png = tk.BooleanVar(value=True)
        self.export_qc_summary = tk.BooleanVar(value=True)
        self.export_full_csv = tk.BooleanVar(value=False)
        self.export_corr_plot = tk.BooleanVar(value=False)
        self.export_overlays = tk.BooleanVar(value=False)
        self.export_parameters = tk.BooleanVar(value=False)

        self.image_paths = []
        self.loaded_image_folder = None
        self.first_raw = None
        self.first_img8 = None  # 当前预览帧的 8-bit 图像，用于显示、画 ROI、纹理检查
        self.current_fullres_img8 = None  # 用于动态缩放的原始分辨率图
        self.display_img = None
        self.display_scale = 1.0
        self.photo = None
        self._resize_after_id = None
        self._has_shown_resize_hint = False

        # 暗色模式基础（可切换色板）
        self.dark_mode = tk.BooleanVar(value=False)

        # 图像缩放状态
        self.zoom_factor = 1.0          # 相对于原始图像的缩放倍率
        self.auto_fit_enabled = True    # 是否跟随窗口自动适应

        if hasattr(self, "preview_scale_var"):
            try:
                self.preview_scale_var.set("")
            except Exception:
                pass

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
        self.tooltips = []
        self.ui_queue = queue.Queue()

        # In-app results viewer (Tier 0)
        self.results_df = None
        self.results_groups = None
        self.viewer_figure = None
        self.viewer_canvas = None
        self.viewer_toolbar = None

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

        self.configure_ui_style()
        self.build_ui()
        self.configure_final_window_limits()
        self.start_ui_queue_polling()

    # ---------- UI ----------

    def configure_initial_window(self):
        # 高 DPI / 缩放感知（Windows 实验室笔记本常见 125%-200% 缩放）
        try:
            self.root.tk.call("tk", "scaling", 1.0)  # 先重置，避免 Tk 内部缩放导致控件重叠
        except Exception:
            pass

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1480, max(1180, screen_w - 120))
        height = min(920, max(740, screen_h - 120))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(1140, 720)

    def configure_final_window_limits(self):
        self.root.update_idletasks()
        # 给一个更宽松的最小尺寸，避免在普通科研笔记本上启动就感觉拥挤
        self.root.minsize(1120, 740)

    def add_tooltip(self, widget, text):
        self.tooltips.append(ToolTip(widget, text))
        return widget

    def get_int_setting(self, var, label):
        try:
            return int(var.get())
        except (tk.TclError, TypeError, ValueError):
            raise RuntimeError(f"{label}必须是整数。")

    def get_float_setting(self, var, label):
        try:
            return float(var.get())
        except (tk.TclError, TypeError, ValueError):
            raise RuntimeError(f"{label}必须是数字。")

    def configure_ui_style(self):
        self.style = ttk.Style(self.root)
        try:
            if "clam" in self.style.theme_names():
                self.style.theme_use("clam")
        except tk.TclError:
            pass

        self._apply_color_palette()

        base_font = ("Microsoft YaHei UI", 9)
        title_font = ("Microsoft YaHei UI", 10, "bold")
        primary_font = ("Microsoft YaHei UI", 10, "bold")
        step_font = ("Microsoft YaHei UI", 9, "bold")

        self.root.configure(background=self.ui_bg)
        self.root.option_add("*Font", base_font)
        self.style.configure(".", font=base_font)
        self.style.configure("App.TFrame", background=self.ui_bg)
        self.style.configure("Panel.TFrame", background=self.panel_bg)
        self.style.configure("Card.TFrame", background=self.card_bg)
        self.style.configure("TLabel", background=self.card_bg, foreground=self.text_color)
        self.style.configure("Hint.TLabel", background=self.card_bg, foreground=self.muted_color)
        self.style.configure("Key.TLabel", background=self.card_bg, font=step_font, foreground=self.key_color)
        self.style.configure("Warning.TLabel", background=self.card_bg, font=step_font, foreground=self.warning_color)
        self.style.configure("StepTitle.TLabel", background=self.card_bg, font=step_font, foreground=self.text_color)
        self.style.configure("TLabelframe", background=self.card_bg, bordercolor=self.border_color, relief="solid")
        self.style.configure("TLabelframe.Label", background=self.ui_bg, foreground=self.text_color, font=title_font)
        self.style.configure("TButton", padding=(10, 5))
        self.style.configure("Compact.TButton", padding=(8, 4))
        self.style.configure("Primary.TButton", font=primary_font, padding=(14, 8), foreground="#ffffff", background=self.primary_color)
        self.style.map(
            "Primary.TButton",
            foreground=[("disabled", "#d9d9d9"), ("active", "#ffffff")],
            background=[("disabled", "#8fa8bf"), ("active", self.primary_active), ("pressed", "#074b8a")],
        )
        self.style.configure("TEntry", padding=(4, 3))
        self.style.configure("TCombobox", padding=(4, 3))
        self.style.configure("Treeview", rowheight=24, background=self.card_bg, fieldbackground=self.card_bg)
        self.style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _apply_color_palette(self):
        """集中管理浅色/暗色配色，便于后续完整暗色模式切换。"""
        if self.dark_mode.get():
            # 暗色主题（实验室长时间使用更护眼）
            self.ui_bg = "#1e2937"
            self.panel_bg = "#334155"
            self.card_bg = "#475569"
            self.border_color = "#64748b"
            self.primary_color = "#3b82f6"
            self.primary_active = "#2563eb"
            self.warning_color = "#f87171"
            self.key_color = "#e0f2fe"
            self.text_color = "#e2e8f0"
            self.muted_color = "#94a3b8"
        else:
            # 浅色主题（默认）
            self.ui_bg = "#eef2f7"
            self.panel_bg = "#f8fafc"
            self.card_bg = "#ffffff"
            self.border_color = "#cbd5e1"
            self.primary_color = "#0b6fcb"
            self.primary_active = "#095aa5"
            self.warning_color = "#b91c1c"
            self.key_color = "#0f3f6e"
            self.text_color = "#0f172a"
            self.muted_color = "#475569"

    def toggle_dark_mode(self):
        """切换暗色/浅色模式，并尝试刷新结果预览图的配色。"""
        is_dark = self.dark_mode.get()
        self.dark_mode.set(not is_dark)
        self._apply_color_palette()

        self.configure_ui_style()

        if hasattr(self, "log_text"):
            self.log_text.configure(bg="#0f172a", fg="#e5e7eb", insertbackground="#e5e7eb")

        # 刷新结果预览器（matplotlib）
        if hasattr(self, "results_df") and self.results_df is not None:
            try:
                self._refresh_viewer_for_dark_mode()
            except Exception:
                pass

        self.root.update_idletasks()
        if hasattr(self, "dark_mode_btn"):
            self.dark_mode_btn.configure(text="浅色模式" if self.dark_mode.get() else "暗色模式")
        self.log("已切换显示模式。" if self.dark_mode.get() else "已恢复默认显示模式。")

    def _refresh_viewer_for_dark_mode(self):
        """当暗色模式切换时，重新绘制当前结果预览图以匹配新主题。"""
        if not hasattr(self, "results_df") or self.results_df is None:
            return
        if hasattr(self, "viewer_figure") and self.viewer_figure is not None:
            # 简单做法：重新调用 show_results_viewer
            try:
                self.show_results_viewer(self.results_df, self.results_groups or [])
            except Exception:
                pass

    def build_ui(self):
        self.root.configure(background=self.ui_bg)
        self.main_frame = ttk.Frame(self.root, style="App.TFrame", padding=(10, 8, 10, 8))
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        self._build_project_section(self.main_frame)
        self._build_workspace(self.main_frame)

    def _build_project_section(self, parent):
        self.project_frame = ttk.LabelFrame(parent, text="1. 图像与输出", padding=(8, 4))
        self.project_frame.grid(row=0, column=0, sticky="ew")
        self.project_frame.columnconfigure(1, weight=1)

        image_folder_tip = (
            "选择同一实验、同一视场、按时间顺序命名的图像序列文件夹。"
            "程序会自然排序 tif/tiff/png/jpg/bmp 文件；常见误用是混入不同倍率、不同样品或无关图片。"
        )
        self.image_folder_label = ttk.Label(self.project_frame, text="图像文件夹：", style="Key.TLabel")
        self.image_folder_label.grid(row=0, column=0, sticky="w", pady=1)
        self.add_tooltip(self.image_folder_label, image_folder_tip)
        self.image_folder_entry = ttk.Entry(self.project_frame, textvariable=self.image_folder, width=42)
        self.image_folder_entry.grid(
            row=0, column=1, sticky="ew", padx=(6, 8), pady=1
        )
        self.add_tooltip(self.image_folder_entry, image_folder_tip)
        self.select_image_button = ttk.Button(
            self.project_frame,
            text="选择文件夹",
            command=self.select_image_folder,
            style="Compact.TButton",
        )
        self.select_image_button.grid(row=0, column=2, sticky="ew", pady=1)
        self.add_tooltip(self.select_image_button, image_folder_tip)

        output_folder_tip = (
            "选择结果保存位置；留空或使用默认值时会在图像文件夹下创建输出目录。"
            "建议每个实验单独一个目录，避免覆盖或混淆不同批次的 TXT/PNG/CSV 结果。"
        )
        self.output_folder_label = ttk.Label(self.project_frame, text="输出文件夹：")
        self.output_folder_label.grid(row=1, column=0, sticky="w", pady=1)
        self.add_tooltip(self.output_folder_label, output_folder_tip)
        self.output_folder_entry = ttk.Entry(self.project_frame, textvariable=self.output_folder, width=42)
        self.output_folder_entry.grid(
            row=1, column=1, sticky="ew", padx=(6, 8), pady=1
        )
        self.add_tooltip(self.output_folder_entry, output_folder_tip)
        self.select_output_button = ttk.Button(
            self.project_frame,
            text="选择输出",
            command=self.select_output_folder,
            style="Compact.TButton",
        )
        self.select_output_button.grid(row=1, column=2, sticky="ew", pady=1)
        self.add_tooltip(self.select_output_button, output_folder_tip)

        seq_buttons = ttk.Frame(self.project_frame, style="Card.TFrame")
        seq_buttons.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        seq_buttons.columnconfigure(0, weight=1)

        preview_row = ttk.Frame(seq_buttons, style="Card.TFrame")
        preview_row.grid(row=0, column=0, sticky="ew")
        range_row = ttk.Frame(seq_buttons, style="Card.TFrame")
        range_row.grid(row=1, column=0, sticky="ew", pady=(3, 0))

        self.load_images_button = ttk.Button(
            preview_row,
            text="加载图像序列",
            command=self.load_first_image,
            style="Compact.TButton",
        )
        self.load_images_button.grid(row=0, column=0, padx=(0, 8), pady=1, sticky="w")
        self.add_tooltip(
            self.load_images_button,
            "读取图像文件夹并显示预览帧；首次加载会把分析范围默认设为第 1 帧到最后一帧。"
            "如果换了文件夹，已有 ROI 组会被清空，避免把旧模板误用于新序列。",
        )

        preview_tip = (
            "输入要查看的 1-based 帧号，只影响当前显示和设置起止帧，不会直接改变分析结果。"
            "推荐检查参考帧、变形中段和结束帧，避免把模糊或离开视场的帧纳入分析。"
        )
        self.preview_frame_label = ttk.Label(preview_row, text="预览帧：")
        self.preview_frame_label.grid(row=0, column=1, padx=(0, 3), sticky="w")
        self.add_tooltip(self.preview_frame_label, preview_tip)
        self.preview_frame_entry = ttk.Entry(preview_row, textvariable=self.preview_frame_1based, width=6)
        self.preview_frame_entry.grid(row=0, column=2, padx=(0, 4), sticky="w")
        self.add_tooltip(self.preview_frame_entry, preview_tip)
        self.show_preview_button = ttk.Button(preview_row, text="显示", command=self.go_to_preview_frame, style="Compact.TButton")
        self.show_preview_button.grid(row=0, column=3, padx=(0, 4), sticky="w")
        self.add_tooltip(self.show_preview_button, preview_tip)

        self.prev_frame_button = ttk.Button(preview_row, text="上一帧", command=lambda: self.step_preview_frame(-1), style="Compact.TButton")
        self.prev_frame_button.grid(row=0, column=4, padx=(0, 4), sticky="w")
        self.add_tooltip(self.prev_frame_button, "向前预览一帧，不改变已设置的分析范围；用于快速检查 ROI 是否仍在视场内。")

        self.next_frame_button = ttk.Button(preview_row, text="下一帧", command=lambda: self.step_preview_frame(1), style="Compact.TButton")
        self.next_frame_button.grid(row=0, column=5, padx=(0, 14), sticky="w")
        self.add_tooltip(self.next_frame_button, "向后预览一帧，不改变已设置的分析范围；用于快速检查 ROI 是否仍在视场内。")

        analysis_range_tip = (
            "设置参与批量追踪的起始帧和结束帧，均为 1-based 帧号。"
            "起始帧也是 ROI 模板参考帧；改变起始帧后应在新参考帧重画 ROI，常见误用是先画 ROI 再改参考帧。"
        )
        self.analysis_range_label = ttk.Label(range_row, text="分析范围：", style="Key.TLabel")
        self.analysis_range_label.grid(row=0, column=0, padx=(0, 3), sticky="w")
        self.add_tooltip(self.analysis_range_label, analysis_range_tip)
        self.start_frame_entry = ttk.Entry(range_row, textvariable=self.start_frame_1based, width=6)
        self.start_frame_entry.grid(row=0, column=1, padx=(0, 3), sticky="w")
        self.add_tooltip(self.start_frame_entry, analysis_range_tip)
        ttk.Label(range_row, text="到").grid(row=0, column=2, padx=(0, 3), sticky="w")
        self.end_frame_entry = ttk.Entry(range_row, textvariable=self.end_frame_1based, width=6)
        self.end_frame_entry.grid(row=0, column=3, padx=(0, 8), sticky="w")
        self.add_tooltip(self.end_frame_entry, analysis_range_tip)

        self.set_start_button = ttk.Button(
            range_row,
            text="当前帧设为起始/参考",
            command=self.set_start_to_current,
            style="Compact.TButton",
        )
        self.set_start_button.grid(row=0, column=4, padx=(0, 4), sticky="w")
        self.add_tooltip(
            self.set_start_button,
            "把当前预览帧设为起始/参考帧；ROI 模板必须在这张图上绘制。"
            "如果已经添加 ROI 组，修改参考帧通常需要清空并重画，否则模板和图像可能不对应。",
        )

        self.set_end_button = ttk.Button(range_row, text="当前帧设为结束", command=self.set_end_to_current, style="Compact.TButton")
        self.set_end_button.grid(row=0, column=5, sticky="w")
        self.add_tooltip(
            self.set_end_button,
            "把当前预览帧设为批量追踪的最后一帧。常用于避开断裂后、失焦、样品离开视场或夹具遮挡的后段图像；结束帧不能早于起始帧。",
        )

    def _build_workspace(self, parent):
        workspace = ttk.Frame(parent, style="App.TFrame")
        workspace.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        workspace.columnconfigure(0, weight=4)   # 图像区占更多
        workspace.columnconfigure(1, weight=2)   # 右侧分析区在宽屏时也能合理扩展，避免过度拥挤
        workspace.rowconfigure(0, weight=1)

        left = ttk.Frame(workspace, style="App.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        self._build_scrollable_controls(left)
        self._build_image_section(left)
        self._build_analysis_section(workspace)

    def _build_scrollable_controls(self, parent):
        self.controls_frame = ttk.Frame(parent, style="App.TFrame")
        self.controls_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.controls_frame.columnconfigure(0, weight=1)
        self.controls_frame.rowconfigure(0, weight=1)

        self.controls_canvas = tk.Canvas(
            self.controls_frame,
            height=230,   # 控制区可滚动；把更多首屏高度留给图像画布
            bg=self.ui_bg,
            highlightthickness=1,
            highlightbackground=self.border_color,
            borderwidth=0,
        )
        controls_scrollbar = ttk.Scrollbar(self.controls_frame, orient=tk.VERTICAL, command=self.controls_canvas.yview)
        self.controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        self.controls_canvas.grid(row=0, column=0, sticky="ew")
        controls_scrollbar.grid(row=0, column=1, sticky="ns")

        self.controls_panel = ttk.Frame(self.controls_canvas, style="Panel.TFrame", padding=(0, 0, 4, 0))
        self.controls_window = self.controls_canvas.create_window((0, 0), window=self.controls_panel, anchor="nw")
        self.controls_panel.bind(
            "<Configure>",
            lambda _event: self.controls_canvas.configure(scrollregion=self.controls_canvas.bbox("all")),
        )
        self.controls_canvas.bind(
            "<Configure>",
            lambda event: self.controls_canvas.itemconfigure(self.controls_window, width=event.width),
        )

        self._build_measure_section(self.controls_panel)
        self._build_roi_section(self.controls_panel)

    def _build_measure_section(self, parent):
        measure_frame = ttk.LabelFrame(parent, text="2. 测量设置", padding=(10, 8))
        measure_frame.grid(row=0, column=0, sticky="ew")
        measure_frame.columnconfigure(7, weight=1)

        strain_mode_tip = (
            "选择两组 ROI 中心距离用于计算应变的方向。自动判断会根据 ROI1/ROI2 的相对位置选择 x、y 或两点距离；"
            "横向/纵向适合严格水平或垂直标距，两点距离适合倾斜标距。误选方向会改变 L0、应变符号和泊松比解释。"
        )
        self.strain_mode_label = ttk.Label(measure_frame, text="应变方向", style="Key.TLabel")
        self.strain_mode_label.grid(row=0, column=0, sticky="w", padx=(0, 4), pady=2)
        self.add_tooltip(self.strain_mode_label, strain_mode_tip)
        self.strain_mode_box = ttk.Combobox(
            measure_frame,
            textvariable=self.strain_mode_display,
            values=list(STRAIN_MODE_LABEL_TO_VALUE.keys()),
            width=12,
            state="readonly",
        )
        self.strain_mode_box.grid(row=0, column=1, sticky="w", padx=(0, 14), pady=2)
        self.strain_mode_box.bind("<<ComboboxSelected>>", self.sync_strain_mode_from_display)
        self.add_tooltip(self.strain_mode_box, strain_mode_tip)

        tracking_preset_tip = (
            "选择一组追踪阈值预设。标准适合多数清晰散斑序列；低质量图像会放宽相关阈值；快速变形会扩大搜索和应变跳变容许。"
            "这些是软件启发式设置，不等同于材料学置信度；修改高级参数后会变为自定义。"
        )
        self.tracking_preset_label = ttk.Label(measure_frame, text="追踪模式", style="Key.TLabel")
        self.tracking_preset_label.grid(row=0, column=2, sticky="w", padx=(0, 4), pady=2)
        self.add_tooltip(self.tracking_preset_label, tracking_preset_tip)
        self.tracking_preset_box = ttk.Combobox(
            measure_frame,
            textvariable=self.tracking_preset,
            values=list(TRACKING_PRESETS.keys()) + ["自定义"],
            width=12,
            state="readonly",
        )
        self.tracking_preset_box.grid(row=0, column=3, sticky="w", padx=(0, 14), pady=2)
        self.tracking_preset_box.bind("<<ComboboxSelected>>", self.apply_tracking_preset)
        self.add_tooltip(self.tracking_preset_box, tracking_preset_tip)
        self.preset_status_label = ttk.Label(measure_frame, textvariable=self.preset_status_var, style="Hint.TLabel")
        self.preset_status_label.grid(
            row=0, column=4, columnspan=4, sticky="w", pady=2
        )
        self.add_tooltip(self.preset_status_label, tracking_preset_tip)

        pixel_size_tip = (
            "填写图像标定比例，单位 mm/px；留空时只按像素标距计算应变，工程应变本身仍为无量纲。"
            "只有在需要记录物理标距或复核像素尺寸时填写；常见误用是把 px/mm 写成 mm/px。"
        )
        self.pixel_size_label = ttk.Label(measure_frame, text="像素尺寸 mm/px，可空")
        self.pixel_size_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=(0, 4), pady=2)
        self.add_tooltip(self.pixel_size_label, pixel_size_tip)
        self.pixel_size_entry = ttk.Entry(measure_frame, textvariable=self.pixel_size_mm, width=9)
        self.pixel_size_entry.grid(row=1, column=2, sticky="w", padx=(0, 14), pady=2)
        self.add_tooltip(self.pixel_size_entry, pixel_size_tip)
        auto_align_tip = (
            "勾选后，绘制 ROI2 结束时会按当前/自动方向把两个 ROI 中心线水平或垂直对齐，适合拉伸标距应严格沿 x 或 y 的实验。"
            "不勾选则保留手动画出的 ROI 位置，适合倾斜标距或确实不应强制对齐的图像。"
        )
        self.auto_align_roi2_check = ttk.Checkbutton(measure_frame, text="绘制 ROI2 后自动对齐", variable=self.auto_align_roi2)
        self.auto_align_roi2_check.grid(
            row=1, column=3, columnspan=2, sticky="w", pady=2
        )
        self.add_tooltip(self.auto_align_roi2_check, auto_align_tip)

        self.advanced_toggle_btn = ttk.Button(
            measure_frame,
            text="显示高级设置",
            command=self.toggle_advanced_settings,
            style="Compact.TButton",
        )
        self.advanced_toggle_btn.grid(row=1, column=5, columnspan=2, sticky="w", padx=(12, 0), pady=2)
        self.add_tooltip(
            self.advanced_toggle_btn,
            "展开或收起追踪阈值、纹理质量和导出 overlay 等高级参数。首次使用建议先用预设；只有在 QC 或 overlay 显示追踪不稳定时再调整。",
        )

        self.advanced_frame = ttk.LabelFrame(measure_frame, text="高级设置", padding=(10, 8))
        self.advanced_frame.grid(row=2, column=0, columnspan=8, sticky="ew", pady=(8, 0))
        self._build_advanced_controls()
        self.advanced_frame.grid_remove()

    def _build_advanced_controls(self):
        advanced_fields = [
            (
                "search_radius_entry",
                "搜索半径 px",
                self.search_radius,
                7,
                "在上一帧 ROI 周围搜索模板匹配候选位置的半径，单位 px。调大可容忍更大帧间位移，但更慢且更容易误匹配；调小更严格，但真实位移超过半径时会失败。",
            ),
            (
                "hard_corr_entry",
                "严格接受阈值",
                self.hard_corr,
                7,
                "两个 ROI 的归一化相关系数都高于该值时才直接接受。调大更保守、拒绝更多低质量帧；调小可减少 NaN，但误接受风险升高。范围应在 -1 到 1。",
            ),
            (
                "soft_corr_entry",
                "弱接受阈值",
                self.soft_corr,
                7,
                "启用自适应弱接受时使用的较低相关阈值，必须不高于严格接受阈值。调小可挽回困难帧，但需要依赖应变连续性和 FB 检查控制误匹配。",
            ),
            (
                "max_frame_strain_jump_entry",
                "单帧应变突变上限",
                self.max_frame_strain_jump,
                8,
                "限制相邻有效帧工程应变的最大跳变；留空会禁用该连续性检查。调大可容忍快速变形，调小会更容易拒绝真实突变或噪声尖峰。",
            ),
            (
                "fb_tolerance_entry",
                "FB 容差 px",
                self.fb_tolerance_px,
                7,
                "前后向一致性检查的允许误差，单位 px。调小更严格、可减少漂移；调大接受更多候选但误匹配风险增加。仅在启用 FB 检查时生效。",
            ),
            (
                "template_alpha_entry",
                "模板跟随系数",
                self.template_alpha,
                7,
                "接受新位置后更新模板的权重，0 表示几乎保持旧模板，1 表示完全换成当前帧 patch。调大适合外观逐渐变化，但过大可能累积漂移。",
            ),
            (
                "min_texture_std_entry",
                "最小灰度标准差",
                self.min_texture_std,
                8,
                "ROI 纹理质量提醒阈值，低于该灰度标准差说明区域可能太平坦。调大更严格；调小会放过低纹理区域，但相关匹配可能不稳定。",
            ),
            (
                "min_texture_contrast_entry",
                "最小 P95-P5 对比度",
                self.min_texture_contrast,
                8,
                "ROI 灰度 P95-P5 对比度提醒阈值，用于发现散斑/纹理不足。调大更保守；调小可接受低对比图，但需结合 QC 和 overlay 复查。",
            ),
            (
                "max_saturated_frac_entry",
                "最大近黑/近白比例",
                self.max_saturated_frac,
                8,
                "ROI 中近黑或近白饱和像素比例上限。调小会更早提示曝光问题；调大可放过饱和区域，但饱和纹理会削弱相关匹配可靠性。范围 0 到 1。",
            ),
            (
                "overlay_every_entry",
                "overlay 间隔",
                self.overlay_every,
                7,
                "勾选导出追踪 overlay 时，每隔多少帧保存一张叠加检查图。数值调小检查更密但文件更多；调大文件少但可能漏掉短暂漂移。",
            ),
        ]
        for idx, (attr_name, label, variable, width, tooltip) in enumerate(advanced_fields):
            row = idx // 3
            col = (idx % 3) * 2
            label_widget = ttk.Label(
                self.advanced_frame,
                text=label,
                style="Key.TLabel" if idx < 4 else "TLabel",
            )
            label_widget.grid(row=row, column=col, sticky="w", padx=(0, 4), pady=3)
            self.add_tooltip(label_widget, tooltip)
            entry = ttk.Entry(self.advanced_frame, textvariable=variable, width=width)
            entry.grid(
                row=row, column=col + 1, sticky="w", padx=(0, 14), pady=3
            )
            setattr(self, attr_name, entry)
            self.add_tooltip(entry, tooltip)

        option_row = (len(advanced_fields) + 2) // 3
        adaptive_tip = (
            "勾选后，严格相关未通过但弱相关、应变连续性和 FB 检查通过的帧可被 adaptive 接受。"
            "不勾选时只接受严格相关帧，更保守但可能产生更多 NaN。"
        )
        self.enable_adaptive_check = ttk.Checkbutton(self.advanced_frame, text="启用自适应弱接受", variable=self.enable_adaptive)
        self.enable_adaptive_check.grid(
            row=option_row, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        self.add_tooltip(self.enable_adaptive_check, adaptive_tip)
        template_follow_tip = (
            "勾选后，每个接受帧都会按模板跟随系数更新 ROI 模板，适合亮度或形貌逐渐变化的序列。"
            "不勾选则始终更接近参考模板，漂移风险较低，但大变形或光照变化时可能更容易拒绝。"
        )
        self.use_prev_frame_template_check = ttk.Checkbutton(
            self.advanced_frame,
            text="使用前一帧模板跟随",
            variable=self.use_prev_frame_template,
        )
        self.use_prev_frame_template_check.grid(
            row=option_row, column=2, columnspan=2, sticky="w", pady=(6, 0)
        )
        self.add_tooltip(self.use_prev_frame_template_check, template_follow_tip)
        fb_tip = (
            "勾选后会把当前候选 patch 反向匹配回上一有效帧，并用 FB 容差判断一致性。"
            "不勾选可减少计算和避免过严拒绝，但自适应接受缺少一层误匹配保护。"
        )
        self.enable_fb_check_check = ttk.Checkbutton(self.advanced_frame, text="前后向一致性检查", variable=self.enable_fb_check)
        self.enable_fb_check_check.grid(
            row=option_row, column=4, columnspan=2, sticky="w", pady=(6, 0)
        )
        self.add_tooltip(self.enable_fb_check_check, fb_tip)

    def _build_roi_section(self, parent):
        group_frame = ttk.LabelFrame(parent, text="3. ROI 设置", padding=(10, 8))
        group_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        group_frame.columnconfigure(0, weight=1)

        tool_row = ttk.Frame(group_frame, style="Card.TFrame")
        tool_row.grid(row=0, column=0, sticky="ew")
        self.roi1_button = ttk.Button(tool_row, text="画 ROI 1", command=lambda: self.set_roi_mode(1), style="Compact.TButton")
        self.roi1_button.grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")
        self.add_tooltip(
            self.roi1_button,
            "切换到 ROI 1 绘制模式；在参考帧上按住鼠标左键拖出矩形。"
            "建议覆盖清晰散斑或稳定纹理，避免边界、反光、裂纹尖端或会消失的区域。",
        )
        self.roi2_button = ttk.Button(tool_row, text="画 ROI 2", command=lambda: self.set_roi_mode(2), style="Compact.TButton")
        self.roi2_button.grid(row=0, column=1, padx=(0, 12), pady=2, sticky="w")
        self.add_tooltip(
            self.roi2_button,
            "切换到 ROI 2 绘制模式；ROI 2 与 ROI 1 的中心距就是虚拟引伸计初始标距 L0。"
            "两个 ROI 太近会放大噪声，太远则更容易受视场边界或局部非均匀变形影响。",
        )
        self.align_x_button = ttk.Button(tool_row, text="水平对齐→横向应变", command=lambda: self.align_current_pair("x", set_mode=True), style="Compact.TButton")
        self.align_x_button.grid(row=1, column=0, columnspan=2, padx=(0, 6), pady=2, sticky="w")
        self.add_tooltip(
            self.align_x_button,
            "强制 ROI1/ROI2 中心 y 坐标相同，并把应变方向设为 x。"
            "适合左右分开的标距；如果实际标距不是水平的，强制对齐会改变物理测量方向。",
        )
        self.align_y_button = ttk.Button(tool_row, text="垂直对齐→纵向应变", command=lambda: self.align_current_pair("y", set_mode=True), style="Compact.TButton")
        self.align_y_button.grid(row=1, column=2, columnspan=2, padx=(0, 6), pady=2, sticky="w")
        self.add_tooltip(
            self.align_y_button,
            "强制 ROI1/ROI2 中心 x 坐标相同，并把应变方向设为 y。"
            "适合上下分开的标距；如果实际标距不是垂直的，强制对齐会改变物理测量方向。",
        )

        form_row = ttk.Frame(group_frame, style="Card.TFrame")
        form_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        group_name_tip = (
            "给当前 ROI 组命名，留空会自动使用 G01、G02 等名称。"
            "建议用样品位置或重复编号命名，避免多个 ROI 组导出后难以追溯。"
        )
        self.group_name_label = ttk.Label(form_row, text="组名：")
        self.group_name_label.grid(row=0, column=0, padx=(0, 4), pady=2, sticky="w")
        self.add_tooltip(self.group_name_label, group_name_tip)
        self.group_name_entry = ttk.Entry(form_row, textvariable=self.group_name_var, width=13)
        self.group_name_entry.grid(row=0, column=1, padx=(0, 12), pady=2, sticky="w")
        self.add_tooltip(self.group_name_entry, group_name_tip)
        role_tip = (
            "选择该 ROI 组在泊松比导出中的角色。普通组只导出自身应变；拉伸方向和横向方向成对存在时才会导出泊松比。"
            "误用风险：把同一物理方向同时标为轴向和横向，会让泊松比没有明确物理意义。"
        )
        self.roi_role_label = ttk.Label(form_row, text="角色：", style="Key.TLabel")
        self.roi_role_label.grid(row=0, column=2, padx=(0, 4), pady=2, sticky="w")
        self.add_tooltip(self.roi_role_label, role_tip)
        self.roi_role_box = ttk.Combobox(
            form_row,
            textvariable=self.roi_role_display,
            values=list(ROI_ROLE_LABEL_TO_VALUE.keys()),
            width=10,
            state="readonly",
        )
        self.roi_role_box.grid(row=0, column=3, padx=(0, 12), pady=2, sticky="w")
        self.roi_role_box.bind("<<ComboboxSelected>>", self.sync_roi_role_from_display)
        self.add_tooltip(self.roi_role_box, role_tip)
        self.add_group_button = ttk.Button(form_row, text="添加当前 ROI 为一组", command=self.add_current_group, style="Compact.TButton")
        self.add_group_button.grid(row=1, column=0, columnspan=4, pady=(4, 2), sticky="w")
        self.add_tooltip(
            self.add_group_button,
            "把当前 ROI1/ROI2 保存为一组虚拟引伸计；每组会独立追踪并导出应变曲线。"
            "添加前请确认两个 ROI 位于同一参考帧，且中心距 L0 与目标测量方向一致。",
        )

        action_row = ttk.Frame(group_frame, style="Card.TFrame")
        action_row.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.update_group_button = ttk.Button(action_row, text="更新选中组", command=self.update_selected_group, style="Compact.TButton")
        self.update_group_button.grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")
        self.add_tooltip(
            self.update_group_button,
            "用当前 ROI1/ROI2 覆盖列表中选中的组；适合发现 ROI 位置、方向或角色设置不合适后修正。"
            "误点会改变该组后续分析模板，建议更新前先载入并确认选中组。",
        )
        self.load_group_button = ttk.Button(action_row, text="载入选中组", command=self.load_selected_group, style="Compact.TButton")
        self.load_group_button.grid(row=0, column=1, padx=(0, 6), pady=2, sticky="w")
        self.add_tooltip(
            self.load_group_button,
            "把列表中选中的 ROI 组载回当前编辑状态，便于检查、微调或更新。"
            "载入本身不会改变导出结果，只有随后点击更新选中组才会覆盖原组。",
        )
        self.delete_group_button = ttk.Button(action_row, text="删除选中组", command=self.delete_selected_group, style="Compact.TButton")
        self.delete_group_button.grid(row=0, column=2, padx=(0, 6), pady=2, sticky="w")
        self.add_tooltip(
            self.delete_group_button,
            "从列表中删除选中的 ROI 组；不会删除已经导出的文件，但本次重新分析时该组不再参与计算。"
            "如果用于泊松比，删除轴向或横向组会导致泊松比无法导出。",
        )
        self.clear_rois_button = ttk.Button(action_row, text="清除当前 ROI", command=self.clear_current_rois, style="Compact.TButton")
        self.clear_rois_button.grid(row=1, column=0, padx=(0, 6), pady=2, sticky="w")
        self.add_tooltip(
            self.clear_rois_button,
            "只清空当前正在编辑的 ROI1/ROI2；已经添加到列表中的 ROI 组不受影响。"
            "适合重画当前框，若要移除已保存的组请使用删除选中组。",
        )

        tree_frame = ttk.Frame(group_frame, style="Card.TFrame")
        tree_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        tree_frame.columnconfigure(0, weight=1)
        columns = ("name", "role", "selected", "actual", "L0", "dx", "dy", "roi1", "roi2")
        # 保留水平滚动，首屏优先显示按钮和图像，不让列表请求宽度撑爆窗口。
        self.group_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=4)
        for col, width in [
            ("name", 56), ("role", 56), ("selected", 48), ("actual", 48), ("L0", 56),
            ("dx", 48), ("dy", 48), ("roi1", 90), ("roi2", 90)
        ]:
            self.group_tree.heading(col, text=col)
            self.group_tree.column(col, width=width, minwidth=42, anchor="center", stretch=True)
        self.group_tree.grid(row=0, column=0, sticky="ew")
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.group_tree.xview)
        self.group_tree.configure(xscrollcommand=tree_scroll_x.set)
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        self.group_tree.bind("<Double-1>", lambda event: self.load_selected_group())
        self.group_tree.bind("<Button-3>", self._show_group_tree_context_menu)  # 右键菜单
        self.add_tooltip(
            self.group_tree,
            "显示已添加的 ROI 组、角色、实际方向和 L0。双击载入，右键可载入/更新/删除选中组。",
        )

    def _build_image_section(self, parent):
        self.image_frame = ttk.LabelFrame(parent, text="图像区：拖动画当前 ROI；绿色线为已添加的 ROI 组", padding=4)
        self.image_frame.grid(row=1, column=0, sticky="nsew")
        self.image_frame.columnconfigure(0, weight=1)
        self.image_frame.rowconfigure(1, weight=1)  # row 0 will be toolbar

        # === 图像工具栏（微交互 + 专业感）===
        img_toolbar = ttk.Frame(self.image_frame, style="Card.TFrame")
        img_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 3))

        self.btn_zoom_out = ttk.Button(img_toolbar, text="−", command=lambda: self.zoom_image(1/1.25), style="Compact.TButton", width=3)
        self.btn_zoom_out.pack(side=tk.LEFT, padx=(0, 2))
        self.add_tooltip(self.btn_zoom_out, "缩小预览（快捷键建议：Ctrl + -）")

        self.btn_zoom_in = ttk.Button(img_toolbar, text="+", command=lambda: self.zoom_image(1.25), style="Compact.TButton", width=3)
        self.btn_zoom_in.pack(side=tk.LEFT, padx=(0, 4))
        self.add_tooltip(self.btn_zoom_in, "放大预览（快捷键建议：Ctrl + +）")

        self.btn_fit = ttk.Button(img_toolbar, text="适应", command=self.fit_image_to_view, style="Compact.TButton", width=6)
        self.btn_fit.pack(side=tk.LEFT, padx=(0, 2))
        self.add_tooltip(self.btn_fit, "将图像缩放以完整显示在当前图像区内")

        self.btn_1to1 = ttk.Button(img_toolbar, text="1:1", command=self.show_image_1to1, style="Compact.TButton", width=4)
        self.btn_1to1.pack(side=tk.LEFT, padx=(0, 6))
        self.add_tooltip(self.btn_1to1, "以原始像素比例显示（100%），最适合精细观察散斑")

        self.zoom_label_var = tk.StringVar(value="100%")
        self.zoom_label = ttk.Label(img_toolbar, textvariable=self.zoom_label_var, width=7, anchor="center")
        self.zoom_label.pack(side=tk.LEFT, padx=(4, 8))

        ttk.Label(img_toolbar, text="提示：拖动窗口边缘可自动提升预览清晰度", style="Hint.TLabel").pack(side=tk.LEFT, padx=4)

        self.canvas = tk.Canvas(self.image_frame, bg="#111827", cursor="crosshair", highlightthickness=0, width=560, height=260)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

        # 滚轮缩放（跨平台处理）
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)       # Windows
        self.canvas.bind("<Button-4>", self._on_mouse_wheel)         # Linux scroll up
        self.canvas.bind("<Button-5>", self._on_mouse_wheel)         # Linux scroll down

        self.add_tooltip(
            self.canvas,
            "在参考帧上拖动画 ROI。滚轮可缩放，拖动窗口边缘可提升预览清晰度。",
        )

    def _build_analysis_section(self, parent):
        self.analysis_frame = ttk.LabelFrame(parent, text="4. 分析与导出", padding=(8, 8))
        self.analysis_frame.grid(row=0, column=1, sticky="nsew")   # 允许水平伸展，宽屏时不那么局促
        self.analysis_frame.columnconfigure(0, weight=1)

        workflow_frame = ttk.LabelFrame(self.analysis_frame, text="新手流程", padding=(8, 6))
        workflow_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.workflow_step_texts = [
            "1. 选择图像文件夹和输出文件夹",
            "2. 加载图像序列，确认预览帧",
            "3. 设置起始/结束帧；起始帧也是参考帧",
            "4. 画 ROI1/ROI2，对齐后添加 ROI 组",
            "5. 确认导出内容，点击开始分析",
        ]
        self.workflow_labels = []
        workflow_compact = " → ".join(["选文件", "加载", "设范围", "加 ROI", "开始分析"])
        label = ttk.Label(workflow_frame, text=workflow_compact, style="StepTitle.TLabel", wraplength=340)
        label.pack(anchor="w", pady=1)
        self.workflow_labels.append(label)
        self.workflow_hint_var = tk.StringVar(
            value="下一步：在参考帧画 ROI；泊松比需轴向/横向各一组。"
        )
        ttk.Label(
            workflow_frame,
            textvariable=self.workflow_hint_var,
            style="Hint.TLabel",
            justify=tk.LEFT,
            wraplength=340,
        ).pack(anchor="w", pady=(2, 0))

        action_frame = ttk.LabelFrame(self.analysis_frame, text="准备好后", padding=(8, 6))
        action_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        action_frame.columnconfigure(0, weight=1)
        self.start_button = ttk.Button(
            action_frame,
            text="开始分析并导出结果",
            command=self.start_processing,
            style="Primary.TButton",
        )
        self.start_button.grid(row=0, column=0, sticky="ew")
        self.add_tooltip(
            self.start_button,
            "点击后开始分析：程序会先检查图像、分析范围、ROI 组和导出选项；通过后批量追踪 ROI，并导出勾选的 TXT/PNG/CSV/OPJU 结果。"
            "开始后请等待完成，若参数错误会先弹窗提示而不改变核心数据。",
        )
        self.export_hint_label = ttk.Label(
            action_frame,
            text="开始前请确认参考帧、ROI 方向和导出内容；错误方向会导致 L0 或应变解释异常。",
            style="Warning.TLabel",
            justify=tk.LEFT,
            wraplength=340,
        )
        self.export_hint_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.add_tooltip(
            self.export_hint_label,
            "这是开始分析前的重点检查区。若不确定方向或 ROI 质量，先导出 QC 摘要、相关系数曲线或 overlay 图片进行复核。",
        )

        export_frame = ttk.LabelFrame(self.analysis_frame, text="导出内容", padding=(10, 8))
        export_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        export_frame.columnconfigure(0, weight=1)
        export_frame.columnconfigure(1, weight=1)

        # 快速预设按钮（科研常用组合）—— 使用 grid 以避免与下方 checkbutton 冲突
        preset_bar = ttk.Frame(export_frame, style="Card.TFrame")
        preset_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Button(preset_bar, text="科研推荐", command=self._apply_research_preset, style="Compact.TButton", width=9).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(preset_bar, text="快速查看", command=self._apply_quick_view_preset, style="Compact.TButton", width=9).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(preset_bar, text="全部导出", command=self._apply_all_export_preset, style="Compact.TButton", width=9).pack(side=tk.LEFT)

        # 使用更宽松的垂直布局 + 更好间距，缓解 cramped 感觉
        export_options = [
            ("Origin TXT（三列核心数据）", self.export_origin_txt, "勾选后导出 Frame、EngineeringStrain、TrueStrain 三列文本，适合直接导入 Origin；不勾选则不生成最小核心数据表。"),
            ("Origin OPJU 项目（直接导入 OriginPro）", self.export_origin_opju, "勾选后启动/连接 OriginPro 并保存 ezDIC_results.opju；需要 OriginPro 2021+ 和 originpro 包，不满足环境时可能失败但不会取消已有 TXT/PNG 导出。"),
            ("工程应变 PNG", self.export_engineering_png, "勾选后为每组 ROI 输出工程应变-帧数曲线；不勾选可减少文件数量，但少了快速查看趋势的图。"),
            ("QC 摘要 TXT", self.export_qc_summary, "勾选后输出接受帧、拒绝帧、自适应接受和相关系数统计；建议保留，用于判断数据是否可用于科研结论。"),
            ("完整 CSV", self.export_full_csv, "勾选后输出完整追踪数据和 ROI 坐标历史；文件较大，适合复查、调试或二次分析，不建议只依赖它做快速汇报。"),
            ("相关系数曲线 PNG", self.export_corr_plot, "勾选后输出相关系数随帧变化曲线；用于发现局部失焦、遮挡或纹理丢失导致的追踪质量下降。"),
            ("追踪 overlay 图片", self.export_overlays, "勾选后按 overlay 间隔保存叠加图，方便肉眼检查 ROI 漂移；间隔太小会生成大量图片。"),
            ("参数与接受统计", self.export_parameters, "勾选后记录当前阈值、搜索半径、接受模式和导出设置，便于论文、报告或重复实验时追溯。"),
        ]
        self.export_checkbuttons = []
        for idx, (text, variable, tooltip) in enumerate(export_options):
            checkbutton = tk.Checkbutton(
                export_frame,
                text=text,
                variable=variable,
                anchor="w",
                justify=tk.LEFT,
                wraplength=190,
                bg=self.card_bg,
                fg=self.text_color,
                activebackground=self.card_bg,
                activeforeground=self.text_color,
                selectcolor=self.card_bg,
                relief=tk.FLAT,
                borderwidth=0,
                highlightthickness=0,
            )
            # 从 row=1 开始，双列排布减少首屏纵向占位。
            checkbutton.grid(row=idx // 2 + 1, column=idx % 2, sticky="w", padx=4, pady=2)
            self.add_tooltip(checkbutton, tooltip)
            self.export_checkbuttons.append(checkbutton)

        status_frame = ttk.LabelFrame(self.analysis_frame, text="运行状态", padding=(8, 6))
        status_frame.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        status_frame.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(status_frame, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.status_var = tk.StringVar(value="未加载图像")
        ttk.Label(status_frame, textvariable=self.status_var, style="Hint.TLabel", wraplength=340).grid(row=1, column=0, sticky="w")

        # 预览缩放信息（动态重采样时更新，让用户知道当前看到的是什么分辨率）
        self.preview_scale_var = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.preview_scale_var, style="Hint.TLabel", foreground="#64748b").grid(row=2, column=0, sticky="w", pady=(1, 0))

        self.log_text = tk.Text(
            self.analysis_frame,
            width=38,
            height=4,   # 略微增加默认高度，配合 viewer 时信息更易读
            wrap=tk.WORD,
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief=tk.FLAT,
            padx=8,
            pady=6,
        )
        self.log_text.grid(row=4, column=0, sticky="nsew")

        # 给日志和预览器合理的垂直分配，避免互相遮挡
        # row 4 (log) 给较大权重，row 5 (viewer) 给固定合理高度，防止整体窗口被撑爆
        self.analysis_frame.rowconfigure(4, weight=3)
        self.analysis_frame.rowconfigure(5, weight=0)   # viewer 由内容决定高度

        # === Tier 0: In-app results viewer (collapsible) ===
        self.viewer_frame = ttk.LabelFrame(self.analysis_frame, text="结果曲线预览（分析完成后显示，可交互）", padding=(8, 6))
        self.viewer_frame.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        self.viewer_frame.columnconfigure(0, weight=1)

        self.viewer_placeholder = ttk.Label(
            self.viewer_frame,
            text="分析完成后自动显示各 ROI 组的工程应变曲线（可缩放、平移）。\n"
                 "若定义了 axial + transverse 角色，可切换查看泊松比曲线。",
            style="Hint.TLabel",
            justify=tk.LEFT,
            wraplength=360,
        )
        self.viewer_placeholder.grid(row=0, column=0, sticky="ew", pady=8)

        viewer_btns = ttk.Frame(self.viewer_frame, style="Card.TFrame")
        viewer_btns.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.viewer_export_btn = ttk.Button(
            viewer_btns,
            text="导出当前图",
            command=self.export_viewer_figure,
            style="Compact.TButton",
            state=tk.DISABLED,
        )
        self.viewer_export_btn.grid(row=0, column=0, padx=(0, 6))
        self.viewer_clear_btn = ttk.Button(
            viewer_btns,
            text="清除预览",
            command=self.clear_viewer,
            style="Compact.TButton",
            state=tk.DISABLED,
        )
        self.viewer_clear_btn.grid(row=0, column=1)

        # The actual matplotlib canvas will be created on demand inside viewer_content_frame
        self.viewer_content_frame = ttk.Frame(self.viewer_frame, style="Card.TFrame")
        self.viewer_content_frame.grid(row=2, column=0, sticky="ew")
        self.viewer_content_frame.columnconfigure(0, weight=1)
        # 高度由 row weight + Figure 尺寸共同控制（已在 workspace 和 analysis_frame 权重中处理）
        self.viewer_frame.grid_remove()

        # Move notice down one row
        notice_frame = ttk.Frame(self.analysis_frame, style="Card.TFrame")
        notice_frame.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        notice_frame.columnconfigure(0, weight=1)
        ttk.Label(
            notice_frame,
            text=f"Developed by {APP_DEVELOPER} | DOI: {APP_DOI}",
            foreground="#555555",
            justify=tk.LEFT,
            wraplength=320,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.usage_notice_button = ttk.Button(
            notice_frame,
            text="About / Citation",
            command=self.show_usage_notice,
            style="Compact.TButton",
        )
        self.usage_notice_button.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.add_tooltip(
            self.usage_notice_button,
            "查看开发者署名、推荐引用格式、DOI 和授权使用说明；写论文、报告或共享结果前建议确认引用信息。",
        )

        # 暗色模式切换（基础实现，便于长时间实验使用）
        self.dark_mode_btn = ttk.Button(
            notice_frame,
            text="暗色模式",
            command=self.toggle_dark_mode,
            style="Compact.TButton",
            width=8,
        )
        self.dark_mode_btn.grid(row=1, column=1, sticky="e", padx=(8, 0), pady=(4, 0))
        self.add_tooltip(self.dark_mode_btn, "切换暗色/浅色界面（实验室长时间使用更护眼）。")

    def sync_strain_mode_from_display(self, event=None):
        label = self.strain_mode_display.get()
        self.strain_mode.set(STRAIN_MODE_LABEL_TO_VALUE.get(label, "auto"))

    def sync_strain_mode_display(self):
        value = self.strain_mode.get()
        self.strain_mode_display.set(STRAIN_MODE_VALUE_TO_LABEL.get(value, "自动判断"))

    def sync_roi_role_from_display(self, event=None):
        label = self.roi_role_display.get()
        self.roi_role.set(ROI_ROLE_LABEL_TO_VALUE.get(label, "none"))

    def sync_roi_role_display(self):
        value = normalize_roi_role(self.roi_role.get())
        self.roi_role.set(value)
        self.roi_role_display.set(ROI_ROLE_VALUE_TO_LABEL.get(value, "普通"))

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
        messagebox.showinfo("About / Citation / Usage Notice", USAGE_NOTICE)

    # ---------- 日志和文件 ----------

    def log(self, msg):
        self.log_text.insert(tk.END, str(msg) + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def show_completion_and_open_output_folder(self, done_msg, output_dir):
        messagebox.showinfo("完成", done_msg)
        try:
            open_output_folder(output_dir)
        except Exception as exc:
            self.log(f"无法自动打开结果目录：{exc}")

    def clear_sequence_dependent_state(self):
        self.roi1 = None
        self.roi2 = None
        self.current_roi_index = 1
        self.drag_start = None
        self.temp_rect_id = None
        self.roi_groups.clear()
        self.next_group_idx = 1
        self.group_name_var.set("")
        self.refresh_group_tree()

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

        new_image_paths = collect_images(folder)
        if not new_image_paths:
            messagebox.showerror("未找到图像", "该文件夹中没有找到 tif/tiff/png/jpg/bmp 图像。")
            return

        old_state = {
            "image_paths": self.image_paths,
            "loaded_image_folder": self.loaded_image_folder,
            "first_raw": self.first_raw,
            "first_img8": self.first_img8,
            "display_img": self.display_img,
            "display_scale": self.display_scale,
            "photo": self.photo,
            "preview": self.preview_frame_1based.get(),
            "start": self.start_frame_1based.get(),
            "end": self.end_frame_1based.get(),
            "current_preview_index": self.current_preview_index,
        }

        n = len(new_image_paths)
        folder_key = os.path.normcase(os.path.abspath(folder))

        # 如果用户还没设置范围，默认 1 到最后一帧。
        if self.end_frame_1based.get() <= 1:
            self.end_frame_1based.set(n)

        self.image_paths = new_image_paths
        self.preview_frame_1based.set(max(1, min(self.preview_frame_1based.get(), n)))
        self.start_frame_1based.set(max(1, min(self.start_frame_1based.get(), n)))
        self.end_frame_1based.set(max(1, min(self.end_frame_1based.get(), n)))

        try:
            self.load_preview_frame(self.preview_frame_1based.get() - 1)
            if self.loaded_image_folder != folder_key:
                self.clear_sequence_dependent_state()
                self.loaded_image_folder = folder_key
                self.show_image()
            self.log(f"找到 {n} 张图像。")
            self.log(f"当前预览：第 {self.current_preview_index + 1} 帧 / 共 {n} 帧")
        except Exception as exc:
            self.image_paths = old_state["image_paths"]
            self.loaded_image_folder = old_state["loaded_image_folder"]
            self.first_raw = old_state["first_raw"]
            self.first_img8 = old_state["first_img8"]
            self.display_img = old_state["display_img"]
            self.display_scale = old_state["display_scale"]
            self.photo = old_state["photo"]
            self.preview_frame_1based.set(old_state["preview"])
            self.start_frame_1based.set(old_state["start"])
            self.end_frame_1based.set(old_state["end"])
            self.current_preview_index = old_state["current_preview_index"]
            self.show_image()
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
        self.current_fullres_img8 = self.first_img8.copy()

        self.display_img = None
        self.display_scale = 1.0
        self.zoom_factor = 1.0
        self.auto_fit_enabled = True
        self.root.update_idletasks()
        self._rescale_display_to_current_size()
        if self.display_img is None:
            self.display_img, self.display_scale = get_display_image(self.first_img8, max_w=1280, max_h=820)
            self.zoom_factor = self.display_scale
            self.show_image()
        self._update_zoom_label()
        self._update_image_toolbar_state()

        # 绑定一次 resize 监听（只绑一次）
        self._bind_image_resize_handler()
        self.status_var.set(
            f"预览第 {index0 + 1}/{n} 帧：{os.path.basename(path)} | "
            f"分析范围 {self.start_frame_1based.get()}–{self.end_frame_1based.get()}"
        )
        self._update_preview_scale_label()
        self.log(f"已显示第 {index0 + 1} 帧：{path}")
        self.log(f"图像尺寸：{self.first_img8.shape[1]} × {self.first_img8.shape[0]} px")

    def go_to_preview_frame(self):
        if not self.image_paths:
            self.load_first_image()
            return

        try:
            idx = self.get_int_setting(self.preview_frame_1based, "预览帧") - 1
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
        s = self.get_int_setting(self.start_frame_1based, "起始帧") - 1
        e = self.get_int_setting(self.end_frame_1based, "结束帧") - 1

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

    def _bind_image_resize_handler(self):
        """只绑定一次，监听图像区尺寸变化，实现窗口拉大后自动提高预览分辨率。"""
        if getattr(self, "_image_resize_bound", False):
            return
        self._image_resize_bound = True

        def on_image_frame_configure(event):
            if self.current_fullres_img8 is None:
                return
            # 防抖：用户拖拽窗口时不要狂刷
            if self._resize_after_id:
                try:
                    self.root.after_cancel(self._resize_after_id)
                except Exception:
                    pass
            self._resize_after_id = self.root.after(180, self._rescale_display_to_current_size)

        # 绑在 image_frame 上更稳（它会随窗口变化）
        self.image_frame.bind("<Configure>", on_image_frame_configure, add="+")

    def _rescale_display_to_current_size(self):
        """根据当前图像区可用空间重新计算显示图像（支持窗口拉大获得更高细节）。"""
        if self.current_fullres_img8 is None:
            return

        # 如果用户正在手动缩放，则不要自动覆盖
        if not getattr(self, "auto_fit_enabled", True):
            return

        try:
            self.root.update_idletasks()
            cw = max(200, self.canvas.winfo_width())
            ch = max(150, self.canvas.winfo_height())
        except Exception:
            cw, ch = 900, 620

        target_w = max(200, cw - 8)
        target_h = max(150, ch - 8)

        new_disp, new_scale = get_display_image(self.current_fullres_img8, max_w=target_w, max_h=target_h)

        old_h, old_w = (self.display_img.shape[:2] if self.display_img is not None else (0, 0))
        if self.display_img is None or abs(new_disp.shape[0] - old_h) > 2 or abs(new_disp.shape[1] - old_w) > 2:
            self.display_img = new_disp
            self.display_scale = new_scale
            self.zoom_factor = new_scale   # 同步 zoom_factor
            self.show_image()
            self._update_preview_scale_label()
            self._update_zoom_label()

            if not self._has_shown_resize_hint:
                self._has_shown_resize_hint = True
                self.log("提示：拉大窗口可自动提高预览分辨率，便于精细绘制 ROI。")

    def _update_preview_scale_label(self):
        """在状态区显示当前预览图像的缩放比例（对科研判断细节很有用）。"""
        if self.display_scale is None or self.display_img is None:
            self.preview_scale_var.set("")
            return
        try:
            scale_pct = self.display_scale * 100
            if scale_pct >= 99.5:
                text = "预览：原始分辨率"
            else:
                text = f"预览缩放：{scale_pct:.0f}%"
            self.preview_scale_var.set(text)
        except Exception:
            self.preview_scale_var.set("")

    # ========== 图像工具栏相关方法 ==========

    # ========== 图像缩放核心逻辑 ==========

    def zoom_image(self, factor):
        """按倍率手动缩放（支持工具栏 +/- 按钮）。"""
        if self.current_fullres_img8 is None:
            return

        self.auto_fit_enabled = False
        new_factor = max(0.1, min(8.0, self.zoom_factor * factor))
        self.zoom_factor = new_factor

        self._apply_manual_zoom()

    def _apply_manual_zoom(self):
        """根据当前 zoom_factor 重新生成显示图像。"""
        if self.current_fullres_img8 is None:
            return

        h, w = self.current_fullres_img8.shape[:2]
        target_w = int(w * self.zoom_factor)
        target_h = int(h * self.zoom_factor)

        if target_w < 50 or target_h < 50:
            target_w, target_h = 50, 50

        disp = cv2.resize(self.current_fullres_img8, (target_w, target_h), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(disp, cv2.COLOR_GRAY2RGB)

        self.display_img = rgb
        self.display_scale = self.zoom_factor
        self.show_image()
        self._update_preview_scale_label()
        self._update_zoom_label()

    def fit_image_to_view(self):
        """强制将当前图像适应当前图像区大小，并恢复自动适应模式。"""
        if self.current_fullres_img8 is None:
            return
        self.auto_fit_enabled = True
        self._rescale_display_to_current_size()
        self._update_preview_scale_label()
        self._update_zoom_label()

    def show_image_1to1(self):
        """以 1:1 原始像素比例显示，并进入手动缩放模式。"""
        if self.current_fullres_img8 is None:
            return
        self.auto_fit_enabled = False
        self.zoom_factor = 1.0

        h, w = self.current_fullres_img8.shape[:2]
        rgb = cv2.cvtColor(self.current_fullres_img8, cv2.COLOR_GRAY2RGB)
        self.display_img = rgb
        self.display_scale = 1.0
        self.show_image()
        self._update_preview_scale_label()
        self._update_zoom_label()
        self.log("已切换为 1:1 原始比例显示。")

    def _update_zoom_label(self):
        """更新工具栏上的缩放百分比显示。"""
        if hasattr(self, "zoom_label_var"):
            pct = int(round(getattr(self, "display_scale", 1.0) * 100))
            self.zoom_label_var.set(f"{pct}%")
        self._update_image_toolbar_state()

    def _update_image_toolbar_state(self):
        """根据是否有图像 + 是否正在处理，控制工具栏按钮状态。"""
        has_image = self.current_fullres_img8 is not None
        can_use = has_image and not getattr(self, "is_processing", False)
        for attr in ("btn_zoom_in", "btn_zoom_out", "btn_fit", "btn_1to1"):
            if hasattr(self, attr):
                try:
                    getattr(self, attr).config(state=tk.NORMAL if can_use else tk.DISABLED)
                except Exception:
                    pass

    def _on_mouse_wheel(self, event):
        """支持鼠标滚轮缩放，围绕鼠标指针位置进行（专业图像工具标准行为）。"""
        if self.current_fullres_img8 is None:
            return

        # 确定缩放方向（跨平台）
        if event.num == 4 or event.delta > 0:
            factor = 1.2
        elif event.num == 5 or event.delta < 0:
            factor = 1 / 1.2
        else:
            return

        self.auto_fit_enabled = False

        # 计算鼠标在当前显示图上的位置。canvasx/canvasy 会考虑当前滚动偏移。
        view_x, view_y = event.x, event.y
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # 当前显示尺寸
        if self.display_img is None:
            return
        disp_h, disp_w = self.display_img.shape[:2]

        # 鼠标在原始图像坐标中的位置（使用当前 display_scale）
        inv_scale = 1.0 / self.display_scale
        img_x = cx * inv_scale
        img_y = cy * inv_scale

        # 应用新的缩放因子
        new_zoom = max(0.05, min(10.0, self.zoom_factor * factor))
        self.zoom_factor = new_zoom

        # 重新计算目标显示尺寸
        orig_h, orig_w = self.current_fullres_img8.shape[:2]
        new_disp_w = int(orig_w * self.zoom_factor)
        new_disp_h = int(orig_h * self.zoom_factor)

        if new_disp_w < 30 or new_disp_h < 30:
            return

        disp = cv2.resize(self.current_fullres_img8, (new_disp_w, new_disp_h), interpolation=cv2.INTER_AREA)
        self.display_img = cv2.cvtColor(disp, cv2.COLOR_GRAY2RGB)
        self.display_scale = self.zoom_factor

        self.show_image()
        self._update_preview_scale_label()
        self._update_zoom_label()

        # 尝试保持鼠标指向的原始位置在缩放后仍大致在鼠标附近（简单版本）
        # 计算新位置
        new_cx = img_x * self.zoom_factor
        new_cy = img_y * self.zoom_factor

        # 将画布滚动到使 (new_cx, new_cy) 接近原鼠标位置
        try:
            self.canvas.xview_moveto(max(0, min(1, (new_cx - view_x) / new_disp_w)))
            self.canvas.yview_moveto(max(0, min(1, (new_cy - view_y) / new_disp_h)))
        except Exception:
            pass

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

        self.drag_start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if self.temp_rect_id is not None:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None

    def on_mouse_drag(self, event):
        if self.drag_start is None:
            return

        x0, y0 = self.drag_start
        x1 = self.canvas.canvasx(event.x)
        y1 = self.canvas.canvasy(event.y)

        if self.temp_rect_id is not None:
            self.canvas.delete(self.temp_rect_id)

        color = "red" if self.current_roi_index == 1 else "cyan"
        self.temp_rect_id = self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=2)

    def on_mouse_up(self, event):
        if self.first_img8 is None or self.drag_start is None:
            return

        x0, y0 = self.drag_start
        x1 = self.canvas.canvasx(event.x)
        y1 = self.canvas.canvasy(event.y)
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
            "role": normalize_roi_role(self.roi_role.get()),
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

        if group["L0"] <= 0 or not np.isfinite(group["L0"]):
            messages.append(
                "L0 无效（≤0），两个 ROI 中心重合或计算错误，无法计算应变。请重新绘制。"
            )
        elif group["L0"] < 50:
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
        self.roi_role.set(normalize_roi_role(group.get("role", "none")))
        self.sync_roi_role_display()
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

    def _show_group_tree_context_menu(self, event):
        """为 ROI 组列表提供右键快捷菜单，提升多组操作效率。"""
        iid = self.group_tree.identify_row(event.y)
        if not iid:
            return
        try:
            idx = int(iid)
        except ValueError:
            return
        if idx < 0 or idx >= len(self.roi_groups):
            return

        # 临时选中该行
        self.group_tree.selection_set(iid)

        menu = tk.Menu(self.group_tree, tearoff=0)
        menu.add_command(label="载入选中组", command=self.load_selected_group)
        menu.add_command(label="更新选中组", command=self.update_selected_group)
        menu.add_separator()
        menu.add_command(label="删除选中组", command=self.delete_selected_group)
        menu.tk_popup(event.x_root, event.y_root)

    def refresh_group_tree(self):
        self.group_tree.delete(*self.group_tree.get_children())
        for idx, g in enumerate(self.roi_groups):
            values = (
                g["name"],
                ROI_ROLE_VALUE_TO_LABEL.get(normalize_roi_role(g.get("role", "none")), "普通"),
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
            f"{prefix}组 {group['name']}: role={normalize_roi_role(group.get('role', 'none'))}, "
            f"selected={group['selected_mode']}, "
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
        output_path = Path(self.output_folder.get().strip())
        if output_path.exists() and not output_path.is_dir():
            raise RuntimeError(f"输出路径已存在但不是文件夹：{output_path}")
        if not any(
            var.get()
            for var in [
                self.export_origin_txt,
                self.export_origin_opju,
                self.export_engineering_png,
                self.export_qc_summary,
                self.export_full_csv,
                self.export_corr_plot,
                self.export_overlays,
                self.export_parameters,
            ]
        ):
            raise RuntimeError("请至少选择一种导出内容。")

        start_idx, end_idx = self.get_analysis_indices()
        if end_idx <= start_idx:
            raise RuntimeError("分析范围至少应包含两帧。")

        search_radius = self.get_int_setting(self.search_radius, "搜索半径")
        overlay_every = self.get_int_setting(self.overlay_every, "overlay 保存间隔")
        hard_corr = self.get_float_setting(self.hard_corr, "硬相关阈值")
        soft_corr = self.get_float_setting(self.soft_corr, "软相关下限")
        template_alpha = self.get_float_setting(self.template_alpha, "模板跟随系数")
        fb_tolerance = self.get_float_setting(self.fb_tolerance_px, "FB 容差")
        max_saturated_frac = self.get_float_setting(self.max_saturated_frac, "最大近黑/近白比例")

        if search_radius <= 0:
            raise RuntimeError("搜索半径必须 > 0。")
        if self.export_overlays.get() and overlay_every <= 0:
            raise RuntimeError("overlay 保存间隔必须 > 0。")
        if not (-1 <= hard_corr <= 1):
            raise RuntimeError("硬相关阈值应在 -1 到 1 之间。")
        if not (-1 <= soft_corr <= 1):
            raise RuntimeError("软相关下限应在 -1 到 1 之间。")
        if soft_corr > hard_corr:
            raise RuntimeError("软相关下限不能高于硬相关阈值。")
        if not (0 <= template_alpha <= 1):
            raise RuntimeError("模板跟随系数应在 0 到 1 之间。")
        if fb_tolerance <= 0:
            raise RuntimeError("FB 容差必须 > 0。")
        if not (0 <= max_saturated_frac <= 1):
            raise RuntimeError("最大近黑/近白比例应在 0 到 1 之间。")

        if self.max_frame_strain_jump.get().strip():
            try:
                jump = float(self.max_frame_strain_jump.get().strip())
            except ValueError:
                raise RuntimeError("单帧应变突变上限必须是数字，或者留空禁用。")
            if jump <= 0:
                raise RuntimeError("单帧应变突变上限必须 > 0，或者留空禁用。")

        if self.pixel_size_mm.get().strip():
            try:
                pix = float(self.pixel_size_mm.get().strip())
            except ValueError:
                raise RuntimeError("像素尺寸必须是数字，或者留空。")
            if pix <= 0:
                raise RuntimeError("像素尺寸必须 > 0，或者留空。")

        poisson_enabled = validate_poisson_role_groups(self.roi_groups)
        if poisson_enabled:
            axial_groups, transverse_groups = get_poisson_role_groups(self.roi_groups)
            axial = axial_groups[0]
            transverse = transverse_groups[0]
            if axial.get("actual_mode") == transverse.get("actual_mode"):
                msg = (
                    "泊松比通常需要一组拉伸方向 ROI 和一组横向收缩 ROI。\n\n"
                    f"当前两组 actual_mode 都是 {axial.get('actual_mode')}：\n"
                    f"拉伸方向：{axial.get('name')}\n"
                    f"横向方向：{transverse.get('name')}\n\n"
                    "这可能说明方向选择或 ROI 对齐不合适。是否仍然继续？"
                )
                if not messagebox.askyesno("泊松比方向警告", msg):
                    raise RuntimeError("用户取消：泊松比 ROI 方向可能不合适。")

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

    def build_processing_settings(self):
        start_idx, end_idx = self.get_analysis_indices()
        max_frame_jump = None
        if self.max_frame_strain_jump.get().strip():
            max_frame_jump = float(self.max_frame_strain_jump.get().strip())

        pixel_size_mm = None
        if self.pixel_size_mm.get().strip():
            pixel_size_mm = float(self.pixel_size_mm.get().strip())

        return {
            "output_dir": Path(self.output_folder.get().strip()),
            "image_paths": list(self.image_paths),
            "roi_groups": [dict(group) for group in self.roi_groups],
            "start_idx": start_idx,
            "end_idx": end_idx,
            "search_radius_base": self.get_int_setting(self.search_radius, "搜索半径"),
            "hard_corr": self.get_float_setting(self.hard_corr, "硬相关阈值"),
            "soft_corr": self.get_float_setting(self.soft_corr, "软相关下限"),
            "enable_adaptive": bool(self.enable_adaptive.get()),
            "use_prev_frame_template": bool(self.use_prev_frame_template.get()),
            "template_alpha": self.get_float_setting(self.template_alpha, "模板跟随系数"),
            "max_frame_jump": max_frame_jump,
            "enable_fb_check": bool(self.enable_fb_check.get()),
            "fb_tolerance": self.get_float_setting(self.fb_tolerance_px, "FB 容差"),
            "pixel_size_mm": pixel_size_mm,
            "overlay_every": self.get_int_setting(self.overlay_every, "overlay 保存间隔"),
            "export_origin_txt": bool(self.export_origin_txt.get()),
            "export_origin_opju": bool(self.export_origin_opju.get()),
            "export_engineering_png": bool(self.export_engineering_png.get()),
            "export_qc_summary": bool(self.export_qc_summary.get()),
            "export_full_csv": bool(self.export_full_csv.get()),
            "export_corr_plot": bool(self.export_corr_plot.get()),
            "export_overlays": bool(self.export_overlays.get()),
            "export_parameters": bool(self.export_parameters.get()),
            "image_folder": self.image_folder.get(),
            "tracking_preset": self.tracking_preset.get(),
        }

    def post_to_ui(self, callback):
        self.ui_queue.put(callback)
        return True

    def start_ui_queue_polling(self):
        try:
            self.root.after(50, self.drain_ui_queue)
        except (RuntimeError, tk.TclError):
            pass

    def drain_ui_queue(self):
        while True:
            try:
                callback = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                traceback.print_exc()
        self.start_ui_queue_polling()

    # ---------- 批量处理 ----------

    def start_processing(self):
        if self.is_processing:
            messagebox.showinfo("正在处理", "程序正在处理，请等待当前任务完成。")
            return

        try:
            self.validate_before_processing()
            settings = self.build_processing_settings()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.is_processing = True
        self.progress["value"] = 0
        if hasattr(self, "start_button"):
            self.start_button.config(state=tk.DISABLED)
        self._update_image_toolbar_state()  # 处理中禁用图像工具栏

        thread = threading.Thread(target=self.process_images_thread, args=(settings,), daemon=True)
        thread.start()

    def process_images_thread(self, settings):
        try:
            self.process_images(settings)
        except Exception as exc:
            self.post_to_ui(lambda: messagebox.showerror("处理失败", str(exc)))
            self.post_to_ui(lambda: self.log(traceback.format_exc()))
        finally:
            self.is_processing = False
            if hasattr(self, "start_button"):
                self.post_to_ui(lambda: self.start_button.config(state=tk.NORMAL))
            self.post_to_ui(lambda: self._update_image_toolbar_state())  # 恢复工具栏

    def init_group_states(self, first_img8, groups=None):
        if groups is None:
            groups = self.roi_groups
        states = []

        for group in groups:
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
            if L0 <= 0 or not np.isfinite(L0):
                candidate_strain = np.nan
            else:
                candidate_strain = (candidate_L - L0) / L0

            ok_jump = True
            if np.isfinite(candidate_strain) and np.isfinite(last_valid_strain):
                jump_value = abs(candidate_strain - last_valid_strain)
                if max_frame_jump is not None:
                    ok_jump = jump_value <= max_frame_jump
            else:
                ok_jump = False
                jump_value = float("inf")

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
                # 统一使用 log1p(engineering) 计算 true strain，比 log(L/L0) 在 strain 很小时数值更稳定
                true_strain = math.log1p(strain) if np.isfinite(strain) and (1.0 + strain) > 0 else np.nan

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
            "role": normalize_roi_role(group.get("role", "none")),
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

    def process_images(self, settings=None):
        if settings is None:
            settings = self.build_processing_settings()

        output_dir = settings["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        core_dir = output_dir / "core"
        qc_dir = output_dir / "qc"
        optional_dir = output_dir / "optional"

        start_idx = settings["start_idx"]
        end_idx = settings["end_idx"]
        image_paths = settings["image_paths"]
        image_paths_run = image_paths[start_idx:end_idx + 1]
        roi_groups = settings["roi_groups"]

        search_radius_base = settings["search_radius_base"]
        hard_corr = settings["hard_corr"]
        soft_corr = settings["soft_corr"]

        enable_adaptive = settings["enable_adaptive"]
        use_prev_frame_template = settings["use_prev_frame_template"]
        template_alpha = settings["template_alpha"]

        max_frame_jump = settings["max_frame_jump"]
        enable_fb_check = settings["enable_fb_check"]
        fb_tolerance = settings["fb_tolerance"]
        pixel_size_mm = settings["pixel_size_mm"]
        overlay_every = settings["overlay_every"]

        export_origin_txt = settings["export_origin_txt"]
        export_engineering_png = settings["export_engineering_png"]
        export_qc_summary = settings["export_qc_summary"]
        export_full_csv = settings["export_full_csv"]
        export_corr_plot = settings["export_corr_plot"]
        export_overlays = settings["export_overlays"]
        export_parameters = settings["export_parameters"]
        export_origin_opju = settings["export_origin_opju"]

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

        states = self.init_group_states(first_img8, roi_groups)

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

        self.post_to_ui(lambda: self.log(
            f"开始处理，分析范围：第 {start_idx + 1} 到第 {end_idx + 1} 帧，"
            f"共 {n} 张图，{len(states)} 组 ROI。"
        ))
        self.post_to_ui(lambda: self.status_var.set("正在批量追踪多组 ROI 并计算应变..."))

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
                    self.post_to_ui(lambda v=progress_val: self.progress.config(value=v))
                    self.post_to_ui(lambda m=msg: self.status_var.set(m))
                    self.post_to_ui(lambda m=msg: self.log(m))

        df = pd.DataFrame(all_rows)
        summary = build_qc_summary(df)
        poisson_enabled = poisson_roles_are_configured(roi_groups)
        written_paths = []

        if export_origin_txt or export_engineering_png or export_origin_opju:
            core_dir.mkdir(parents=True, exist_ok=True)

        for group in roi_groups:
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
            write_all_groups_origin_txt(df, all_txt, roi_groups)
            written_paths.append(all_txt)

            mean_txt = core_dir / "strain_mean_groups.txt"
            write_mean_groups_origin_txt(df, roi_groups, mean_txt)
            written_paths.append(mean_txt)

            if poisson_enabled:
                poisson_txt = core_dir / "poisson_ratio.txt"
                write_poisson_ratio_txt(df, roi_groups, poisson_txt)
                written_paths.append(poisson_txt)

        if export_engineering_png:
            combined_fig = core_dir / "engineering_strain_all_groups.png"
            plot_all_groups_engineering_strain(df, roi_groups, combined_fig)
            written_paths.append(combined_fig)

            if poisson_enabled:
                poisson_fig = core_dir / "poisson_ratio.png"
                plot_poisson_ratio(df, roi_groups, poisson_fig)
                written_paths.append(poisson_fig)

        if export_origin_opju:
            opju_path = core_dir / ORIGIN_OPJU_FILENAME
            try:
                write_origin_opju_project(df, roi_groups, opju_path)
            except Exception as exc:
                warning = f"Origin OPJU 项目生成失败：{exc}"
                self.post_to_ui(lambda m=warning: self.log(m))
                self.post_to_ui(lambda m=warning: messagebox.showwarning("Origin OPJU 生成失败", m))
            else:
                written_paths.append(opju_path)

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
            for group in roi_groups:
                gname = group["name"]
                sg = safe_name(gname)
                gdf = df[df["group"] == gname].copy()
                g_csv = group_dir / f"strain_results_{sg}.csv"
                gdf.to_csv(g_csv, index=False, encoding="utf-8-sig")
                written_paths.append(g_csv)

        if export_corr_plot:
            corr_dir = optional_dir / "correlation_plots"
            corr_dir.mkdir(parents=True, exist_ok=True)
            for group in roi_groups:
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
                f.write(f"image_folder = {settings['image_folder']}\n")
                f.write(f"number_of_images_in_analysis_range = {n}\n")
                f.write(f"start_frame_1based = {start_idx + 1}\n")
                f.write(f"end_frame_1based = {end_idx + 1}\n")
                f.write(f"number_of_groups = {len(roi_groups)}\n")
                f.write(f"tracking_preset = {settings['tracking_preset']}\n")
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
                for g in roi_groups:
                    f.write(
                        f"{g['name']}: role={normalize_roi_role(g.get('role', 'none'))}, "
                        f"selected={g['selected_mode']}, actual={g['actual_mode']}, "
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
        mean_export_note = ""
        if export_origin_txt:
            mean_export_note = (
                "\n平均应变文件: core\\strain_mean_groups.txt"
                "\n平均应变列也已写入: core\\strain_all_groups.txt"
            )
        done_msg = (
            f"处理完成。\n"
            f"核心结果已保存到: {core_dir if (export_origin_txt or export_engineering_png or export_origin_opju) else output_dir}\n"
            f"QC 状态: {qc_level}\n"
            f"Rejected frames: {n_rejected}\n"
            f"Adaptive accepted frames: {n_adaptive}"
            f"{mean_export_note}"
        )

        self.post_to_ui(lambda: self.progress.config(value=100))
        self.post_to_ui(lambda: self.status_var.set(f"处理完成，QC 状态：{qc_level}"))
        self.post_to_ui(lambda: self.log(done_msg + "\n" + path_log))
        self.post_to_ui(lambda: self.show_completion_and_open_output_folder(done_msg, output_dir))

        # === Tier 0: populate in-app viewer with final results ===
        try:
            if df is not None and not df.empty and roi_groups:
                self.post_to_ui(lambda: self.show_results_viewer(df, roi_groups))
        except Exception:
            # Viewer failure must never break the main success path
            self.post_to_ui(lambda: self.log("结果预览窗口初始化失败（不影响已导出文件）"))

    # ==========================
    # Tier 0: In-app interactive results viewer
    # ==========================

    def show_results_viewer(self, df, groups):
        """Embed an interactive matplotlib figure showing engineering strain (and optionally Poisson)."""
        if df is None or df.empty:
            return

        # Destroy previous canvas if any
        self.clear_viewer(keep_placeholder=False)
        self.viewer_frame.grid()

        self.results_df = df.copy()
        self.results_groups = groups

        # 检测是否具备泊松比数据（至少有一组 axial + 一组 transverse）
        self._has_poisson = self._detect_poisson_capable(groups, df)

        # 默认显示工程应变
        self._viewer_mode = "strain"  # "strain" or "poisson"

        self._rebuild_viewer_plot()

        # 控制区：模式切换 + 导出
        self._add_viewer_controls()

        # Hide placeholder, enable buttons
        self.viewer_placeholder.grid_remove()
        self.viewer_export_btn.config(state=tk.NORMAL)
        self.viewer_clear_btn.config(state=tk.NORMAL)

        self.log("已更新应用内结果曲线预览（支持缩放、平移、泊松比切换）。")

    # ========== 导出预设 ==========

    def _apply_research_preset(self):
        """科研推荐组合：核心 TXT + PNG + QC + 参数（最常用）"""
        self.export_origin_txt.set(True)
        self.export_engineering_png.set(True)
        self.export_qc_summary.set(True)
        self.export_parameters.set(True)
        self.export_full_csv.set(False)
        self.export_corr_plot.set(False)
        self.export_overlays.set(False)
        self.export_origin_opju.set(False)
        self.log("已应用「科研推荐」导出预设")

    def _apply_quick_view_preset(self):
        """快速查看：只保留最常用的可视化结果"""
        self.export_origin_txt.set(False)
        self.export_engineering_png.set(True)
        self.export_qc_summary.set(True)
        self.export_parameters.set(False)
        self.export_full_csv.set(False)
        self.export_corr_plot.set(False)
        self.export_overlays.set(False)
        self.export_origin_opju.set(False)
        self.log("已应用「快速查看」导出预设")

    def _apply_all_export_preset(self):
        """全部勾选（用于最完整的存档）"""
        for var in [
            self.export_origin_txt, self.export_origin_opju,
            self.export_engineering_png, self.export_qc_summary,
            self.export_full_csv, self.export_corr_plot,
            self.export_overlays, self.export_parameters
        ]:
            var.set(True)
        self.log("已应用「全部导出」预设（注意文件会较多）")

    def _detect_poisson_capable(self, groups, df):
        roles = {normalize_roi_role(g.get("role", "none")) for g in groups}
        has_axial = "axial" in roles
        has_trans = "transverse" in roles
        if not (has_axial and has_trans):
            return False
        # 再检查数据里是否有对应的列（兼容旧结果）
        return "AxialEngineeringStrain" in df.columns or "PoissonRatio" in df.columns

    def _rebuild_viewer_plot(self):
        """根据 self._viewer_mode 重绘嵌入的 matplotlib 图"""
        if self.results_df is None or self.results_df.empty:
            return

        # 清理旧的 canvas（保留 controls）
        for child in list(self.viewer_content_frame.children.values()):
            if child not in (getattr(self, "_viewer_controls", None),):
                try:
                    child.destroy()
                except Exception:
                    pass

        df = self.results_df
        groups = self.results_groups or []

        # 根据窄右栏优化尺寸（约 4.2 英寸宽，高度适中避免遮挡）
        fig = Figure(figsize=(4.2, 2.8), dpi=100)
        ax = fig.add_subplot(111)

        # 暗色模式支持：让内嵌曲线图也跟随主题
        if getattr(self, "dark_mode", None) and self.dark_mode.get():
            fig.patch.set_facecolor("#334155")
            ax.set_facecolor("#334155")
            ax.tick_params(colors="#e2e8f0")
            for spine in ax.spines.values():
                spine.set_color("#64748b")
            ax.yaxis.label.set_color("#e2e8f0")
            ax.xaxis.label.set_color("#e2e8f0")
            ax.title.set_color("#e2e8f0")
            if ax.get_legend():
                for text in ax.get_legend().get_texts():
                    text.set_color("#e2e8f0")

        if self._viewer_mode == "poisson" and self._has_poisson:
            table = build_poisson_ratio_table(df, groups)
            frame = table["Frame"].astype(float)
            ratio = table["PoissonRatio"].astype(float)
            valid = ratio.notna() & np.isfinite(ratio)

            ax.plot(frame, ratio, color="#2ca02c", linewidth=1.2, alpha=0.75, label="Poisson Ratio")
            if valid.any():
                ax.scatter(frame[valid], ratio[valid], color="#2ca02c", s=16, zorder=3)
            invalid = ~valid
            if invalid.any():
                finite = ratio[valid]
                if len(finite) > 0:
                    y_off = float(finite.min()) - 0.08 * (float(finite.max()) - float(finite.min()) or 0.01)
                else:
                    y_off = 0.0
                ax.scatter(frame[invalid], [y_off] * int(invalid.sum()), color="#d62728", marker="x", s=28, label="NaN")

            ax.set_ylabel("Poisson ratio")
            ax.set_title("泊松比曲线（应用内预览）")
        else:
            # 默认：工程应变多组曲线
            has_any = False
            for g in groups:
                gname = g["name"]
                gdf = df[df["group"] == gname]
                if gdf.empty:
                    continue
                has_any = True
                ax.plot(
                    gdf["frame_global_1based"],
                    gdf["engineering_strain"],
                    linewidth=1.1,
                    alpha=0.72,
                    label=gname,
                )
            if not has_any:
                ax.text(0.5, 0.5, "无可显示的有效应变数据", ha="center", va="center", transform=ax.transAxes, fontsize=9)
            else:
                ax.set_ylabel("工程应变 (Engineering strain)")

            ax.set_title("各 ROI 组工程应变曲线（应用内预览）")

        ax.set_xlabel("帧 (Frame)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=7)

        # 再次确保暗色模式下的文字颜色
        if getattr(self, "dark_mode", None) and self.dark_mode.get():
            ax.tick_params(colors="#e2e8f0")
            ax.yaxis.label.set_color("#e2e8f0")
            ax.xaxis.label.set_color("#e2e8f0")
            ax.title.set_color("#e2e8f0")

        fig.tight_layout()

        self.viewer_figure = fig
        self.viewer_canvas = FigureCanvasTkAgg(fig, master=self.viewer_content_frame)
        self.viewer_canvas.draw()
        self.viewer_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        try:
            from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
            self.viewer_toolbar = NavigationToolbar2Tk(self.viewer_canvas, self.viewer_content_frame)
            self.viewer_toolbar.grid(row=1, column=0, sticky="ew")
        except Exception:
            self.viewer_toolbar = None

        # 应用高质量暗色样式（如果开启）
        self._style_viewer_axes_dark(ax)

    def _style_viewer_axes_dark(self, ax):
        """为内嵌结果预览图提供高质量的暗色主题支持。"""
        if not (hasattr(self, "dark_mode") and self.dark_mode.get()):
            return

        try:
            fig = ax.figure
            fig.patch.set_facecolor("#1e2937")
            ax.set_facecolor("#1e2937")

            # 坐标轴和刻度
            ax.tick_params(colors="#cbd5e1", labelsize=8)
            for spine in ax.spines.values():
                spine.set_color("#64748b")
                spine.set_linewidth(0.8)

            # 标签和标题
            ax.xaxis.label.set_color("#e2e8f0")
            ax.yaxis.label.set_color("#e2e8f0")
            ax.title.set_color("#f1f5f9")

            # 网格
            ax.grid(True, alpha=0.25, color="#64748b")

            # 图例
            legend = ax.get_legend()
            if legend:
                legend.get_frame().set_facecolor("#334155")
                legend.get_frame().set_edgecolor("#64748b")
                for text in legend.get_texts():
                    text.set_color("#e2e8f0")
        except Exception:
            pass  # 容错，不影响主流程

    def _add_viewer_controls(self):
        """在 viewer 内部添加模式切换控件（工程应变 / 泊松比）"""
        if hasattr(self, "_viewer_controls") and self._viewer_controls:
            self._viewer_controls.destroy()

        ctrl = ttk.Frame(self.viewer_frame, style="Card.TFrame")
        ctrl.grid(row=3, column=0, sticky="ew", pady=(6, 2))
        self._viewer_controls = ctrl

        ttk.Label(ctrl, text="显示模式：", style="Hint.TLabel").pack(side=tk.LEFT, padx=(8, 4))

        self.viewer_mode_var = tk.StringVar(value=self._viewer_mode)

        def switch_mode():
            new_mode = self.viewer_mode_var.get()
            if new_mode != self._viewer_mode:
                self._viewer_mode = new_mode
                self._rebuild_viewer_plot()

        ttk.Radiobutton(
            ctrl, text="工程应变", variable=self.viewer_mode_var, value="strain",
            command=switch_mode
        ).pack(side=tk.LEFT, padx=4)

        poisson_rb = ttk.Radiobutton(
            ctrl, text="泊松比", variable=self.viewer_mode_var, value="poisson",
            command=switch_mode,
            state=tk.NORMAL if self._has_poisson else tk.DISABLED
        )
        poisson_rb.pack(side=tk.LEFT, padx=4)

        if not self._has_poisson:
            ttk.Label(ctrl, text="（需同时定义 axial + transverse 角色）", style="Hint.TLabel").pack(side=tk.LEFT, padx=6)

    def export_viewer_figure(self):
        if self.viewer_figure is None:
            messagebox.showinfo("无预览", "当前没有可导出的曲线预览。")
            return
        path = filedialog.asksaveasfilename(
            title="导出当前预览图",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("PDF 矢量图", "*.pdf"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            self.viewer_figure.savefig(path, dpi=200, bbox_inches="tight")
            self.log(f"已导出预览图：{path}")
            messagebox.showinfo("导出成功", f"已保存到：\n{path}")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            self.log(f"预览图导出失败：{exc}")

    def clear_viewer(self, keep_placeholder=True):
        """Remove embedded matplotlib widgets and reset state."""
        # 清理 matplotlib 相关
        if self.viewer_toolbar is not None:
            try:
                self.viewer_toolbar.destroy()
            except Exception:
                pass
            self.viewer_toolbar = None

        if self.viewer_canvas is not None:
            try:
                self.viewer_canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self.viewer_canvas = None

        self.viewer_figure = None

        # 清理新增的模式切换控件
        if hasattr(self, "_viewer_controls") and self._viewer_controls:
            try:
                self._viewer_controls.destroy()
            except Exception:
                pass
            self._viewer_controls = None

        self.results_df = None
        self.results_groups = None
        self._has_poisson = False
        self._viewer_mode = "strain"

        # 恢复占位提示
        if keep_placeholder:
            try:
                self.viewer_frame.grid()
                self.viewer_placeholder.grid()
            except Exception:
                pass
            self.viewer_export_btn.config(state=tk.DISABLED)
            self.viewer_clear_btn.config(state=tk.DISABLED)

    def run(self):
        self.root.mainloop()


def main():
    root = tk.Tk()
    app = MultiROIGUI(root)
    app.run()


if __name__ == "__main__":
    main()
