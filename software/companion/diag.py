"""GPU / VRAM diagnostics. pynvml first, nvidia-smi as fallback, never raises."""
import shutil, subprocess


def gpu_info():
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        m = pynvml.nvmlDeviceGetMemoryInfo(h)
        name = pynvml.nvmlDeviceGetName(h)
        drv = pynvml.nvmlSystemGetDriverVersion()
        return {"gpu": name.decode() if isinstance(name, bytes) else name,
                "driver": drv.decode() if isinstance(drv, bytes) else drv,
                "vram_total_mb": m.total // 2**20, "vram_used_mb": m.used // 2**20, "source": "nvml"}
    except Exception:
        pass
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            out = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total,memory.used",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
            name, drv, tot, used = [x.strip() for x in out.splitlines()[0].split(",")]
            return {"gpu": name, "driver": drv, "vram_total_mb": int(tot), "vram_used_mb": int(used),
                    "source": "nvidia-smi"}
        except Exception:
            pass
    return {"gpu": None, "driver": None, "vram_total_mb": None, "vram_used_mb": None, "source": None}


def cuda_ok():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
