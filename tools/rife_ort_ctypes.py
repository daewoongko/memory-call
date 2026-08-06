"""Small ONNX Runtime C-API wrapper for the local RIFE timestep model.

Why this exists
---------------
The age-generation virtual environment contains ONNX Runtime GPU for Python
3.11, but the executable behind that environment is not available to the
Codex sandbox.  The native ONNX Runtime DLL has a stable C ABI, so Python 3.12
can still use it directly through :mod:`ctypes`.

This module intentionally wraps only the calls needed by RIFE.  It targets the
ONNX Runtime 1.20 C API (``ORT_API_VERSION == 20``) and keeps one set of CPU
input/output tensors alive for the lifetime of the process.  Reusing the
preallocated output also avoids allocating an ``OrtValue`` for every frame.

CUDA is best-effort.  If the local CUDA execution-provider DLL cannot be
loaded, session creation continues with the CPU provider and ``provider_error``
records the native error message.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path
from typing import Iterable

import numpy as np


ORT_API_VERSION = 20
ORT_LOGGING_LEVEL_ERROR = 3
ORT_ARENA_ALLOCATOR = 1
ORT_MEM_TYPE_DEFAULT = 0
ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT = 1
ORT_ENABLE_ALL = 99

# ONNX Runtime 1.20 OrtApi table offsets.  The table is append-only, and the
# requested API version is explicitly checked before any offset is used.
_CREATE_ENV = 3
_CREATE_SESSION = 7
_RUN = 9
_CREATE_SESSION_OPTIONS = 10
_SET_SESSION_GRAPH_OPTIMIZATION_LEVEL = 23
_CREATE_TENSOR_WITH_DATA_AS_ORT_VALUE = 49
_CREATE_CPU_MEMORY_INFO = 69


class OrtError(RuntimeError):
    """Raised when an ONNX Runtime C API call returns an OrtStatus."""


def _default_project_root() -> Path:
    configured = os.environ.get("MEMORY_CALL_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def default_rife_model() -> Path:
    """Return the repository-managed arbitrary-timestep RIFE model."""

    return (
        _default_project_root()
        / "backend"
        / "models"
        / "rife"
        / "RIFE_fp32_timestep.onnx"
    )


def default_capi_dir() -> Path:
    configured = os.environ.get("RIFE_ORT_CAPI_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        _default_project_root()
        / ".venv-age"
        / "Lib"
        / "site-packages"
        / "onnxruntime"
        / "capi"
    )


def default_torch_lib_dir() -> Path:
    configured = os.environ.get("RIFE_TORCH_LIB_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        _default_project_root()
        / ".venv-age"
        / "Lib"
        / "site-packages"
        / "torch"
        / "lib"
    )


class RifeOrtSession:
    """Run ``RIFE_fp32_timestep.onnx`` using ONNX Runtime's native C API.

    Parameters
    ----------
    model_path:
        Path to the arbitrary-timestep RIFE ONNX model.
    prefer_cuda:
        Append the CUDA execution provider when its dependencies can load.
        Any provider-load error is retained in :attr:`provider_error`, and a
        CPU session is created instead.
    capi_dir, torch_lib_dir:
        Override locations of ONNX Runtime and CUDA/cuDNN DLLs.
    """

    def __init__(
        self,
        model_path: str | os.PathLike[str],
        *,
        prefer_cuda: bool = True,
        capi_dir: str | os.PathLike[str] | None = None,
        torch_lib_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        if sys.platform != "win32":
            raise OSError("This wrapper currently targets the Windows ORT C ABI.")

        self.model_path = Path(model_path).expanduser().resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(self.model_path)

        self.capi_dir = Path(capi_dir or default_capi_dir()).resolve()
        self.torch_lib_dir = Path(torch_lib_dir or default_torch_lib_dir()).resolve()
        self._dll_dir_handles: list[object] = []
        self._preloaded_dlls: list[ctypes.WinDLL] = []
        self.provider_error: str | None = None
        self.execution_provider = "CPUExecutionProvider"

        self._add_dll_directory(self.capi_dir, required=True)
        self._add_dll_directory(self.torch_lib_dir, required=False)
        self._preload_cuda_dependencies()

        runtime_path = self.capi_dir / "onnxruntime.dll"
        if not runtime_path.is_file():
            raise FileNotFoundError(runtime_path)
        self._dll = ctypes.WinDLL(str(runtime_path))
        self._call = ctypes.WINFUNCTYPE
        self._bind_api()

        self._env = ctypes.c_void_p()
        self._session_options = ctypes.c_void_p()
        self._session = ctypes.c_void_p()
        self._memory_info = ctypes.c_void_p()

        self._check(
            self._create_env(
                ORT_LOGGING_LEVEL_ERROR,
                b"memory-call-rife",
                ctypes.byref(self._env),
            ),
            "CreateEnv",
        )
        self._check(
            self._create_session_options(ctypes.byref(self._session_options)),
            "CreateSessionOptions",
        )
        self._check(
            self._set_graph_optimization(
                self._session_options,
                ORT_ENABLE_ALL,
            ),
            "SetSessionGraphOptimizationLevel",
        )

        if prefer_cuda:
            self._try_append_cuda()

        self._check(
            self._create_session(
                self._env,
                str(self.model_path),
                self._session_options,
                ctypes.byref(self._session),
            ),
            "CreateSession",
        )
        self._check(
            self._create_cpu_memory_info(
                ORT_ARENA_ALLOCATOR,
                ORT_MEM_TYPE_DEFAULT,
                ctypes.byref(self._memory_info),
            ),
            "CreateCpuMemoryInfo",
        )

        self._height: int | None = None
        self._width: int | None = None
        self._input: np.ndarray | None = None
        self._timestep: np.ndarray | None = None
        self._output: np.ndarray | None = None
        self._input_value = ctypes.c_void_p()
        self._timestep_value = ctypes.c_void_p()
        self._output_value = ctypes.c_void_p()

    @property
    def runtime_version(self) -> str:
        return self._runtime_version

    @property
    def provider(self) -> str:
        """Short compatibility alias used by the video builder."""

        return self.execution_provider

    @property
    def frame_size(self) -> tuple[int, int] | None:
        if self._height is None or self._width is None:
            return None
        return self._width, self._height

    def _add_dll_directory(self, directory: Path, *, required: bool) -> None:
        if not directory.is_dir():
            if required:
                raise FileNotFoundError(directory)
            return
        # Keep the returned object alive; closing it removes the directory from
        # Windows' process DLL search path.
        self._dll_dir_handles.append(os.add_dll_directory(str(directory)))

    def _preload_cuda_dependencies(self) -> None:
        """Keep ORT's CUDA dependencies resident before provider loading.

        ONNX Runtime is installed separately from PyTorch here, while the CUDA
        and cuDNN runtime DLLs live in ``torch/lib``.  Explicitly loading the
        direct dependencies makes that arrangement work on machines where the
        loader does not otherwise retain the add_dll_directory search path.
        Failures are intentionally ignored: CUDA remains optional and the
        native provider error gives the useful final diagnosis.
        """

        candidates: Iterable[tuple[Path, str]] = (
            (self.torch_lib_dir, "cudart64_12.dll"),
            (self.torch_lib_dir, "cublasLt64_12.dll"),
            (self.torch_lib_dir, "cublas64_12.dll"),
            (self.torch_lib_dir, "cufft64_11.dll"),
            (self.torch_lib_dir, "cudnn64_9.dll"),
            # cuDNN 9's umbrella DLL resolves these component libraries at
            # runtime instead of declaring them as normal PE imports.
            (self.torch_lib_dir, "cudnn_ops64_9.dll"),
            (self.torch_lib_dir, "cudnn_graph64_9.dll"),
            (self.torch_lib_dir, "cudnn_heuristic64_9.dll"),
            (self.torch_lib_dir, "cudnn_engines_precompiled64_9.dll"),
            (self.torch_lib_dir, "cudnn_engines_runtime_compiled64_9.dll"),
            (self.torch_lib_dir, "cudnn_adv64_9.dll"),
            (self.torch_lib_dir, "cudnn_cnn64_9.dll"),
            (self.capi_dir, "onnxruntime_providers_shared.dll"),
        )
        for directory, name in candidates:
            path = directory / name
            if not path.is_file():
                continue
            try:
                self._preloaded_dlls.append(ctypes.WinDLL(str(path)))
            except OSError:
                # The CUDA provider append call below reports the full ORT
                # error, so do not turn an optional preload into a hard fail.
                pass

    def _bind_api(self) -> None:
        self._dll.OrtGetApiBase.argtypes = []
        self._dll.OrtGetApiBase.restype = ctypes.c_void_p
        base_ptr = self._dll.OrtGetApiBase()
        if not base_ptr:
            raise OrtError("OrtGetApiBase returned NULL")

        base = ctypes.cast(base_ptr, ctypes.POINTER(ctypes.c_void_p))
        get_api = self._call(ctypes.c_void_p, ctypes.c_uint32)(base[0])
        get_version = self._call(ctypes.c_char_p)(base[1])
        version_bytes = get_version()
        self._runtime_version = (
            version_bytes.decode("utf-8", errors="replace")
            if version_bytes
            else "unknown"
        )

        api_ptr = get_api(ORT_API_VERSION)
        if not api_ptr:
            raise OrtError(
                f"ONNX Runtime {self._runtime_version} does not expose C API "
                f"version {ORT_API_VERSION}"
            )
        api = ctypes.cast(api_ptr, ctypes.POINTER(ctypes.c_void_p))

        self._get_error_message = self._call(
            ctypes.c_char_p,
            ctypes.c_void_p,
        )(api[2])
        self._create_env = self._call(
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_void_p),
        )(api[_CREATE_ENV])
        self._create_session = self._call(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )(api[_CREATE_SESSION])
        self._run = self._call(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        )(api[_RUN])
        self._create_session_options = self._call(
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )(api[_CREATE_SESSION_OPTIONS])
        self._set_graph_optimization = self._call(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
        )(api[_SET_SESSION_GRAPH_OPTIMIZATION_LEVEL])
        self._create_tensor = self._call(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int64),
            ctypes.c_size_t,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )(api[_CREATE_TENSOR_WITH_DATA_AS_ORT_VALUE])
        self._create_cpu_memory_info = self._call(
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )(api[_CREATE_CPU_MEMORY_INFO])

    def _status_message(self, status: int | ctypes.c_void_p) -> str:
        if not status:
            return ""
        raw = self._get_error_message(status)
        if not raw:
            return "unknown ONNX Runtime error"
        return raw.decode("utf-8", errors="replace")

    def _check(self, status: int | ctypes.c_void_p, operation: str) -> None:
        if status:
            raise OrtError(f"{operation}: {self._status_message(status)}")

    def _try_append_cuda(self) -> None:
        try:
            append_cuda = self._call(
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_int,
            )(("OrtSessionOptionsAppendExecutionProvider_CUDA", self._dll))
        except (AttributeError, OSError) as exc:
            self.provider_error = f"CUDA export unavailable: {exc}"
            return

        status = append_cuda(self._session_options, 0)
        if status:
            self.provider_error = self._status_message(status)
            return
        self.execution_provider = "CUDAExecutionProvider"

    def _tensor_value(self, array: np.ndarray) -> ctypes.c_void_p:
        if array.dtype != np.float32 or not array.flags.c_contiguous:
            raise TypeError("ORT tensor backing arrays must be C-contiguous float32")

        shape = tuple(int(value) for value in array.shape)
        if shape:
            shape_buffer = (ctypes.c_int64 * len(shape))(*shape)
            shape_pointer = shape_buffer
        else:
            shape_pointer = None

        value = ctypes.c_void_p()
        self._check(
            self._create_tensor(
                self._memory_info,
                ctypes.c_void_p(int(array.ctypes.data)),
                array.nbytes,
                shape_pointer,
                len(shape),
                ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT,
                ctypes.byref(value),
            ),
            "CreateTensorWithDataAsOrtValue",
        )
        return value

    def _ensure_buffers(self, height: int, width: int) -> None:
        if self._height is not None:
            if (height, width) != (self._height, self._width):
                raise ValueError(
                    "A RifeOrtSession has fixed frame dimensions after its first "
                    f"inference: expected {self._width}x{self._height}, got "
                    f"{width}x{height}"
                )
            return

        if height <= 0 or width <= 0:
            raise ValueError(f"Invalid frame size: {width}x{height}")

        self._height = height
        self._width = width
        self._input = np.empty((1, 6, height, width), dtype=np.float32)
        self._timestep = np.empty((), dtype=np.float32)
        self._output = np.empty((1, 3, height, width), dtype=np.float32)
        self._input_value = self._tensor_value(self._input)
        self._timestep_value = self._tensor_value(self._timestep)
        self._output_value = self._tensor_value(self._output)

    @staticmethod
    def _validate_rgb_frame(frame: np.ndarray, label: str) -> None:
        if not isinstance(frame, np.ndarray):
            raise TypeError(f"{label} must be a numpy array")
        if frame.dtype != np.uint8:
            raise TypeError(f"{label} must have dtype uint8, got {frame.dtype}")
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(f"{label} must have shape HxWx3, got {frame.shape}")

    def infer_rgb_uint8(
        self,
        frame0: np.ndarray,
        frame1: np.ndarray,
        timestep: float,
    ) -> np.ndarray:
        """Interpolate two RGB uint8 frames at ``0 < timestep < 1``."""

        self._validate_rgb_frame(frame0, "frame0")
        self._validate_rgb_frame(frame1, "frame1")
        if frame0.shape != frame1.shape:
            raise ValueError(
                f"Input frames must have the same shape: {frame0.shape} != "
                f"{frame1.shape}"
            )
        if not 0.0 < float(timestep) < 1.0:
            raise ValueError("RIFE endpoints are not exact; timestep must satisfy 0 < t < 1")

        height, width = frame0.shape[:2]
        self._ensure_buffers(height, width)
        assert self._input is not None
        assert self._timestep is not None
        assert self._output is not None

        np.multiply(
            frame0.transpose(2, 0, 1),
            np.float32(1.0 / 255.0),
            out=self._input[0, 0:3],
            casting="unsafe",
        )
        np.multiply(
            frame1.transpose(2, 0, 1),
            np.float32(1.0 / 255.0),
            out=self._input[0, 3:6],
            casting="unsafe",
        )
        self._timestep[()] = np.float32(timestep)

        input_names = (ctypes.c_char_p * 2)(b"input", b"timestep")
        input_values = (ctypes.c_void_p * 2)(
            self._input_value.value,
            self._timestep_value.value,
        )
        output_names = (ctypes.c_char_p * 1)(b"output")
        output_values = (ctypes.c_void_p * 1)(self._output_value.value)
        self._check(
            self._run(
                self._session,
                None,
                input_names,
                input_values,
                2,
                output_names,
                1,
                output_values,
            ),
            "Run",
        )
        if output_values[0] != self._output_value.value:
            raise OrtError("Run unexpectedly replaced the preallocated output OrtValue")

        rgb = np.clip(self._output[0].transpose(1, 2, 0), 0.0, 1.0)
        return np.rint(rgb * np.float32(255.0)).astype(np.uint8)

    def interpolate(
        self,
        frame0_rgb_u8: np.ndarray,
        frame1_rgb_u8: np.ndarray,
        timestep: float,
    ) -> np.ndarray:
        """Compatibility alias for :meth:`infer_rgb_uint8`."""

        return self.infer_rgb_uint8(frame0_rgb_u8, frame1_rgb_u8, timestep)


# Compact name for callers that do not need to know the implementation detail.
RifeOrt = RifeOrtSession


def _load_rgb(path: Path) -> np.ndarray:
    import cv2

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"Could not decode image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _save_rgb(path: Path, rgb: np.ndarray) -> None:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)):
        raise OSError(f"Could not write image: {path}")


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=default_rife_model())
    parser.add_argument("--left", type=Path)
    parser.add_argument("--right", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timestep", type=float, default=0.5)
    parser.add_argument("--cpu", action="store_true", help="Do not try CUDA")
    parser.add_argument(
        "--synthetic-size",
        type=int,
        default=64,
        help="Square test size when --left/--right are omitted",
    )
    args = parser.parse_args()

    if (args.left is None) != (args.right is None):
        parser.error("--left and --right must be supplied together")
    if args.output is not None and args.left is None:
        parser.error("--output requires --left and --right")

    if args.left is None:
        size = args.synthetic_size
        left = np.zeros((size, size, 3), dtype=np.uint8)
        right = np.full((size, size, 3), 255, dtype=np.uint8)
    else:
        left = _load_rgb(args.left)
        right = _load_rgb(args.right)

    started = time.perf_counter()
    session = RifeOrtSession(args.model, prefer_cuda=not args.cpu)
    setup_seconds = time.perf_counter() - started
    run_started = time.perf_counter()
    result = session.infer_rgb_uint8(left, right, args.timestep)
    run_seconds = time.perf_counter() - run_started

    if args.output is not None:
        _save_rgb(args.output, result)

    print(f"ONNX Runtime: {session.runtime_version}")
    print(f"Execution provider: {session.execution_provider}")
    if session.provider_error:
        print(f"CUDA fallback reason: {session.provider_error}")
    print(f"Frame size: {left.shape[1]}x{left.shape[0]}")
    print(f"Setup time: {setup_seconds:.3f}s")
    print(f"Inference time: {run_seconds:.3f}s")
    print(
        "Output range: "
        f"{int(result.min())}..{int(result.max())}, mean {float(result.mean()):.3f}"
    )
    if args.output is not None:
        print(f"Saved: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
