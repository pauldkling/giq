# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Multiview child process: Depth Anything 3 on the ``da3`` interpreter.

Invoked by ``MultiviewWorker`` via ``<envs/da3 python> -u -m
giq.workers._multiview_child --model da3-base --weights <dir>`` with this
checkout's ``src`` on ``PYTHONPATH``. Loads the local snapshot the recipe
names, with the hub disabled before anything from the hub ecosystem is
imported, so nothing is fetched.

Per task: decode N images, run the model's own ``inference`` (it resizes
every view to ``process_res`` on the long side, rounded to a multiple of
14, and returns depth, confidence, extrinsics and intrinsics per view at
that size), and return each view as 16-bit PNGs plus its camera. The depth
is real depth along the ray in one shared, arbitrary scale — unless the
task supplied extrinsics, in which case the prediction is aligned to them.
Optionally the model's own GLB export (fused, confidence-filtered point
cloud with camera wireframes) is built in a RAM-backed directory and
returned as bytes; nothing is written to disk.

Wire protocol: see giq.workers._subprocess.
"""

import os
import sys

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from giq.workers._subprocess import (  # noqa: E402
    reserve_ipc_stdout,
    run_ipc_child_loop,
    write_startup_error,
)

# Every view's tokens attend to every other view's, so VRAM grows with the
# total token count — views times (long side / 14) times (short side / 14).
# Both caps bound the registry's VRAM figure: it was measured at 32 square
# views of 504 px, which is exactly MAX_TOKENS. A request over either limit
# is refused before the model sees it, not after it OOMs.
MAX_VIEWS = int(os.environ.get("GIQ_MULTIVIEW_MAX_VIEWS", "32"))
PATCH = 14
DEFAULT_PROCESS_RES = 504
MIN_PROCESS_RES, MAX_PROCESS_RES = 252, 1008
MAX_TOKENS = int(os.environ.get("GIQ_MULTIVIEW_MAX_TOKENS", str(32 * (504 // PATCH) ** 2)))
REF_VIEW_STRATEGIES = ("first", "middle", "saddle_balanced", "saddle_sim_range")
# The model's own GLB defaults: drop the least confident 40% of points, keep
# at most a million.
DEFAULT_CONF_PERCENTILE = 40.0
DEFAULT_MAX_POINTS = 1_000_000
# Where the GLB is assembled: a RAM-backed filesystem when there is one.
_RAM_DIR = "/dev/shm" if os.path.isdir("/dev/shm") else None


def _load(path: str):
    import torch
    from depth_anything_3.api import DepthAnything3  # ty: ignore[unresolved-import]

    if not os.path.isdir(path):
        raise RuntimeError(f"model directory does not exist: {path}")
    net = DepthAnything3.from_pretrained(path)
    return net.to(device=torch.device("cuda")).eval()


def _decode(b64: str):
    import base64
    import io

    from PIL import Image, ImageOps

    return ImageOps.exif_transpose(Image.open(io.BytesIO(base64.b64decode(b64)))).convert("RGB")


def _png_b64(array) -> str:
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="PNG", compress_level=1)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def to_16bit(values):
    """float map → (uint16 map, min, max); a flat map maps to zeros."""
    import numpy as np

    lo, hi = float(values.min()), float(values.max())
    scaled = (values - lo) / (hi - lo) if hi > lo else np.zeros_like(values)
    return (scaled * 65535.0 + 0.5).astype(np.uint16), lo, hi


def _tokens(size: tuple[int, int], process_res: int) -> int:
    """Patch tokens one view costs after the model's own resize (long side to
    ``process_res``, both sides rounded to a multiple of the patch)."""
    w, h = size
    scale = process_res / max(w, h)
    pw = max(1, round(w * scale / PATCH))
    ph = max(1, round(h * scale / PATCH))
    return pw * ph


def _cameras(task: dict, n: int):
    """Task-supplied poses → (extrinsics (N,4,4), intrinsics (N,3,3)) or (None, None)."""
    import numpy as np

    ext, ixt = task.get("extrinsics"), task.get("intrinsics")
    if ext is None and ixt is None:
        return None, None
    if ext is None or ixt is None:
        raise ValueError("extrinsics and intrinsics must be given together")
    ext = np.asarray(ext, dtype=np.float32)
    ixt = np.asarray(ixt, dtype=np.float32)
    if ext.shape == (n, 3, 4):
        full = np.tile(np.eye(4, dtype=np.float32), (n, 1, 1))
        full[:, :3, :] = ext
        ext = full
    if ext.shape != (n, 4, 4) or ixt.shape != (n, 3, 3):
        raise ValueError(f"extrinsics must be ({n},4,4) or ({n},3,4) and intrinsics ({n},3,3)")
    return ext, ixt


def _glb_bytes(prediction, conf_percentile: float, max_points: int) -> bytes:
    import tempfile

    from depth_anything_3.utils.export.glb import (  # ty: ignore[unresolved-import]
        export_to_glb,
    )

    with tempfile.TemporaryDirectory(prefix="giq-mv-", dir=_RAM_DIR) as d:
        path = export_to_glb(
            prediction,
            d,
            conf_thresh_percentile=conf_percentile,
            num_max_points=max_points,
            show_cameras=True,
            export_depth_vis=False,
        )
        with open(path, "rb") as f:
            return f.read()


def _run(net, task: dict) -> dict:
    import base64

    import torch

    images_b64 = task.get("images_b64") or []
    if not images_b64:
        raise ValueError("task needs images_b64")
    if len(images_b64) > MAX_VIEWS:
        raise ValueError(f"{len(images_b64)} views; the limit is {MAX_VIEWS}")
    process_res = int(task.get("process_res") or DEFAULT_PROCESS_RES)
    if not MIN_PROCESS_RES <= process_res <= MAX_PROCESS_RES:
        raise ValueError(f"process_res must be between {MIN_PROCESS_RES} and {MAX_PROCESS_RES}")
    strategy = task.get("ref_view_strategy") or "saddle_balanced"
    if strategy not in REF_VIEW_STRATEGIES:
        raise ValueError(f"ref_view_strategy must be one of {REF_VIEW_STRATEGIES}")

    images = [_decode(b) for b in images_b64]
    tokens = sum(_tokens(im.size, process_res) for im in images)
    if tokens > MAX_TOKENS:
        raise ValueError(
            f"{len(images)} views at {process_res} px is {tokens} tokens; the limit is "
            f"{MAX_TOKENS} (fewer views or a smaller process_res)"
        )
    extrinsics, intrinsics = _cameras(task, len(images))
    try:
        pred = net.inference(
            images,
            extrinsics=extrinsics,
            intrinsics=intrinsics,
            use_ray_pose=bool(task.get("use_ray_pose", False)),
            ref_view_strategy=strategy,
            process_res=process_res,
        )
        views = []
        for i in range(pred.depth.shape[0]):
            d16, dlo, dhi = to_16bit(pred.depth[i])
            view = {
                "index": i,
                "width": int(pred.depth.shape[2]),
                "height": int(pred.depth.shape[1]),
                "depth_b64": _png_b64(d16),
                "depth_min": dlo,
                "depth_max": dhi,
                "extrinsics": pred.extrinsics[i][:3, :4].tolist(),
                "intrinsics": pred.intrinsics[i].tolist(),
            }
            if pred.conf is not None:
                c16, clo, chi = to_16bit(pred.conf[i])
                view.update({"conf_b64": _png_b64(c16), "conf_min": clo, "conf_max": chi})
            views.append(view)
        result = {
            "id": task["id"],
            "views": views,
            "metric": bool(pred.is_metric),
            "process_res": process_res,
        }
        if task.get("glb"):
            glb = _glb_bytes(
                pred,
                float(task.get("conf_percentile") or DEFAULT_CONF_PERCENTILE),
                int(task.get("max_points") or DEFAULT_MAX_POINTS),
            )
            result["glb_b64"] = base64.b64encode(glb).decode("ascii")
        return result
    finally:
        # The caching allocator would otherwise hold the peak of the largest
        # batch for the life of the child; hand it back between tasks.
        torch.cuda.empty_cache()


def main() -> None:
    import argparse

    reserve_ipc_stdout()
    parser = argparse.ArgumentParser()
    # --model names the recipe for log lines; --weights is what loads.
    parser.add_argument("--model", required=True)
    parser.add_argument("--weights", required=True)
    args = parser.parse_args()
    try:
        net = _load(args.weights)
    except Exception as e:  # noqa: BLE001 — report any load failure to parent
        import traceback

        write_startup_error(str(e), traceback.format_exc())
        sys.exit(1)

    def on_run_batch(tasks, params):
        results = []
        for task in tasks:
            try:
                results.append(_run(net, task))
            except Exception as e:  # noqa: BLE001 — per-task error envelope
                results.append({"id": task.get("id", "unknown"), "error": str(e)})
        return results

    run_ipc_child_loop(on_run_batch)


if __name__ == "__main__":
    main()
