"""Image Resolution & Scaling Service for Autonomous Stream Clipper.

Provides high-speed classical resampling algorithms, detail and contrast enhancement filters,
and neural AI super-resolution for upstream preprocessing and quality optimization.
"""

import base64
import io
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

try:
    import onnxruntime as ort
    _ORT_AVAILABLE = True
except ImportError:
    _ORT_AVAILABLE = False

logger = logging.getLogger(__name__)

SUPPORTED_ALGORITHMS = [
    # Classical Resamplers
    "bicubic",
    "lanczos4",
    "bilinear",
    "area",
    "nearest",
    # Enhancement Filters
    "unsharp_mask",
    "clahe",
    "bilateral",
    # Neural AI Super-Resolution
    "neural_subpixel",
]


class ImageScalerService:
    """Scales, resamples, and enhances cropped or full-frame images for downstream CV pipelines."""

    def __init__(
        self,
        scale_factor: float = 2.0,
        algorithm: str = "bicubic",
        sharpen_strength: float = 0.5,
        clahe_clip_limit: float = 2.0,
        denoise_strength: float = 0.0,
        target_w: int = 0,
        target_h: int = 0,
        neural_model_path: Optional[str] = None,
    ):
        self.scale_factor = float(scale_factor or 2.0)
        self.algorithm = (algorithm or "bicubic").lower().strip()
        self.sharpen_strength = float(sharpen_strength if sharpen_strength is not None else 0.5)
        self.clahe_clip_limit = float(clahe_clip_limit if clahe_clip_limit is not None else 2.0)
        self.denoise_strength = float(denoise_strength if denoise_strength is not None else 0.0)
        self.target_w = int(target_w or 0)
        self.target_h = int(target_h or 0)

        # Neural Super-Resolution Session (Phase 2)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.neural_model_path = neural_model_path or os.path.join(
            base_dir, "models", "vision", "super-resolution-10.onnx"
        )
        self.ort_session = None
        self._init_neural_model()

    def _init_neural_model(self):
        """Initializes ONNX super-resolution session if available."""
        if _ORT_AVAILABLE and os.path.exists(self.neural_model_path):
            try:
                self.ort_session = ort.InferenceSession(
                    self.neural_model_path, providers=["CPUExecutionProvider"]
                )
                logger.info("[ImageScaler] Loaded neural super-resolution ONNX from %s", self.neural_model_path)
            except Exception as e:
                logger.warning("[ImageScaler] Failed to initialize neural super-resolution ONNX: %s", e)

    def set_parameters(
        self,
        scale_factor: Optional[float] = None,
        algorithm: Optional[str] = None,
        sharpen_strength: Optional[float] = None,
        clahe_clip_limit: Optional[float] = None,
        denoise_strength: Optional[float] = None,
        target_w: Optional[int] = None,
        target_h: Optional[int] = None,
    ):
        """Hot-reloads scaler parameters on active stream sessions."""
        if scale_factor is not None:
            self.scale_factor = max(0.1, min(8.0, float(scale_factor)))
        if algorithm is not None:
            self.algorithm = str(algorithm).lower().strip()
        if sharpen_strength is not None:
            self.sharpen_strength = max(0.0, min(3.0, float(sharpen_strength)))
        if clahe_clip_limit is not None:
            self.clahe_clip_limit = max(1.0, min(10.0, float(clahe_clip_limit)))
        if denoise_strength is not None:
            self.denoise_strength = max(0.0, min(1.0, float(denoise_strength)))
        if target_w is not None:
            self.target_w = max(0, int(target_w))
        if target_h is not None:
            self.target_h = max(0, int(target_h))

        logger.debug(
            "[ImageScaler] Updated params: scale=%.2f, algo=%s, sharpen=%.2f, clahe=%.2f",
            self.scale_factor, self.algorithm, self.sharpen_strength, self.clahe_clip_limit
        )

    def compute_target_dimensions(self, in_w: int, in_h: int) -> Tuple[int, int]:
        """Calculates destination pixel width and height."""
        if self.target_w > 0 and self.target_h > 0:
            return (self.target_w, self.target_h)
        elif self.target_w > 0:
            aspect = in_h / (in_w or 1)
            return (self.target_w, max(1, int(round(self.target_w * aspect))))
        elif self.target_h > 0:
            aspect = in_w / (in_h or 1)
            return (max(1, int(round(self.target_h * aspect))), self.target_h)
        else:
            out_w = max(1, int(round(in_w * self.scale_factor)))
            out_h = max(1, int(round(in_h * self.scale_factor)))
            return (out_w, out_h)

    def process_frame(self, frame: Image.Image) -> Dict[str, Any]:
        """Executes scaling, enhancement, or neural super-resolution on an input PIL frame."""
        t0 = time.perf_counter()
        in_w, in_h = frame.size
        out_w, out_h = self.compute_target_dimensions(in_w, in_h)

        algo = self.algorithm

        # 1. Neural Super-Resolution Branch (Phase 2)
        if algo in ("neural_subpixel", "fsrcnn", "espcn", "super_resolution"):
            if self.ort_session is not None:
                try:
                    scaled_frame = self._process_neural_super_res(frame, out_w, out_h)
                except Exception as e:
                    logger.warning("[ImageScaler] Neural super-res failed (%s), falling back to Lanczos4", e)
                    scaled_frame = self._process_classical(frame, out_w, out_h, "lanczos4")
            else:
                scaled_frame = self._process_classical(frame, out_w, out_h, "lanczos4")

        # 2. Detail / Contrast Enhancers Branch (Phase 1)
        elif algo in ("unsharp_mask", "clahe", "bilateral"):
            scaled_frame = self._process_enhancement(frame, out_w, out_h, algo)

        # 3. Classical Resamplers Branch (Phase 1)
        else:
            scaled_frame = self._process_classical(frame, out_w, out_h, algo)

        # Optional post-sharpening if requested and not already applied as primary algorithm
        if self.sharpen_strength > 0.05 and algo != "unsharp_mask":
            scaled_frame = self._apply_unsharp_mask(scaled_frame, self.sharpen_strength)

        t1 = time.perf_counter()
        latency_ms = round((t1 - t0) * 1000.0, 2)

        # Generate base64 thumbnail for live in-node UI preview
        scaled_thumbnail_b64 = ""
        try:
            buf = io.BytesIO()
            tw = min(320, scaled_frame.width)
            th = min(240, scaled_frame.height)
            thumb = scaled_frame.resize((tw, th), Image.Resampling.BILINEAR) if (scaled_frame.width != tw or scaled_frame.height != th) else scaled_frame
            thumb.convert("RGB").save(buf, format="JPEG", quality=75)
            scaled_thumbnail_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.debug("[ImageScaler] Failed to encode preview thumbnail: %s", e)

        return {
            "frame": scaled_frame,
            "input_res": f"{in_w}x{in_h}",
            "output_res": f"{scaled_frame.width}x{scaled_frame.height}",
            "scale_factor": round(scaled_frame.width / max(1, in_w), 2),
            "algorithm": self.algorithm,
            "latency_ms": latency_ms,
            "scaled_thumbnail_b64": scaled_thumbnail_b64,
            "timestamp": time.time(),
        }

    def _process_classical(self, frame: Image.Image, out_w: int, out_h: int, algo: str) -> Image.Image:
        """Applies classical interpolation (Lanczos4, Bicubic, Bilinear, Area, Nearest)."""
        if _CV2_AVAILABLE:
            np_img = np.array(frame.convert("RGB"))
            interp_map = {
                "lanczos4": cv2.INTER_LANCZOS4,
                "lanczos": cv2.INTER_LANCZOS4,
                "bicubic": cv2.INTER_CUBIC,
                "cubic": cv2.INTER_CUBIC,
                "bilinear": cv2.INTER_LINEAR,
                "linear": cv2.INTER_LINEAR,
                "area": cv2.INTER_AREA,
                "nearest": cv2.INTER_NEAREST,
            }
            interp = interp_map.get(algo, cv2.INTER_CUBIC)
            resized_np = cv2.resize(np_img, (out_w, out_h), interpolation=interp)
            return Image.fromarray(resized_np)
        else:
            pil_map = {
                "lanczos4": Image.Resampling.LANCZOS,
                "lanczos": Image.Resampling.LANCZOS,
                "bicubic": Image.Resampling.BICUBIC,
                "cubic": Image.Resampling.BICUBIC,
                "bilinear": Image.Resampling.BILINEAR,
                "linear": Image.Resampling.BILINEAR,
                "area": Image.Resampling.BOX,
                "nearest": Image.Resampling.NEAREST,
            }
            resample = pil_map.get(algo, Image.Resampling.BICUBIC)
            return frame.resize((out_w, out_h), resample=resample)

    def _process_enhancement(self, frame: Image.Image, out_w: int, out_h: int, algo: str) -> Image.Image:
        """Applies upscale followed by detail/contrast enhancement filters."""
        # First resize using high-detail Lanczos4 or Bicubic
        base_scaled = self._process_classical(frame, out_w, out_h, "bicubic")

        if algo == "unsharp_mask":
            return self._apply_unsharp_mask(base_scaled, max(0.4, self.sharpen_strength))

        elif algo == "clahe":
            return self._apply_clahe(base_scaled, self.clahe_clip_limit)

        elif algo == "bilateral":
            return self._apply_bilateral(base_scaled, self.denoise_strength)

        return base_scaled

    def _apply_unsharp_mask(self, frame: Image.Image, strength: float) -> Image.Image:
        """Sharpens image edges via unsharp masking."""
        if _CV2_AVAILABLE:
            np_img = np.array(frame.convert("RGB"))
            gaussian = cv2.GaussianBlur(np_img, (0, 0), 2.0)
            sharpened = cv2.addWeighted(np_img, 1.0 + strength, gaussian, -strength, 0)
            return Image.fromarray(np.clip(sharpened, 0, 255).astype(np.uint8))
        else:
            return frame.filter(ImageFilter.UnsharpMask(radius=2, percent=int(strength * 100)))

    def _apply_clahe(self, frame: Image.Image, clip_limit: float) -> Image.Image:
        """Enhances local contrast in dark/shadowed regions (e.g. dimly lit facecams, low-contrast text)."""
        if _CV2_AVAILABLE:
            np_img = np.array(frame.convert("RGB"))
            lab = cv2.cvtColor(np_img, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl, a, b))
            enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2RGB)
            return Image.fromarray(enhanced)
        else:
            enhancer = ImageEnhance.Contrast(frame)
            return enhancer.enhance(1.0 + (clip_limit / 5.0))

    def _apply_bilateral(self, frame: Image.Image, denoise_strength: float) -> Image.Image:
        """Edge-preserving filter that eliminates Twitch HLS compression artifacts and macroblocks."""
        if _CV2_AVAILABLE:
            np_img = np.array(frame.convert("RGB"))
            sigma = int(max(15, min(120, (denoise_strength or 0.5) * 100)))
            denoised = cv2.bilateralFilter(np_img, d=5, sigmaColor=sigma, sigmaSpace=sigma)
            return Image.fromarray(denoised)
        else:
            return frame.filter(ImageFilter.SMOOTH_MORE)

    def _process_neural_super_res(self, frame: Image.Image, out_w: int, out_h: int) -> Image.Image:
        """Executes deep sub-pixel convolutional neural super-resolution via ONNX."""
        # Convert RGB to YCbCr; neural network upscales Y (luminance) channel for crisp sub-pixel detail
        img_ycbcr = frame.convert("YCbCr")
        img_y, img_cb, img_cr = img_ycbcr.split()

        # Neural model requires standardized 224x224 input patch
        y_input = img_y.resize((224, 224), Image.Resampling.BICUBIC)
        y_tensor = np.array(y_input, dtype=np.float32).reshape(1, 1, 224, 224)

        # Forward pass through ONNX (produces 672x672 3x super-resolved luminance)
        input_name = self.ort_session.get_inputs()[0].name
        out_y = self.ort_session.run(None, {input_name: y_tensor})[0][0][0]
        out_y = np.clip(out_y, 0, 255).astype(np.uint8)
        hr_y = Image.fromarray(out_y, mode="L")

        # Bicubic upscale color chroma channels (Cb, Cr) to match 672x672
        hr_cb = img_cb.resize((672, 672), Image.Resampling.BICUBIC)
        hr_cr = img_cr.resize((672, 672), Image.Resampling.BICUBIC)

        # Recompose 3x neural enhanced image
        hr_ycbcr = Image.merge("YCbCr", (hr_y, hr_cb, hr_cr)).convert("RGB")

        # Fit to desired destination target dimensions if different from 672x672
        if (hr_ycbcr.width, hr_ycbcr.height) != (out_w, out_h):
            hr_ycbcr = hr_ycbcr.resize((out_w, out_h), Image.Resampling.LANCZOS)

        return hr_ycbcr
