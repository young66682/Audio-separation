"""通过 libsndfile 写出音频的 Demucs 命令行封装。

新版 TorchAudio 会把 save() 委托给 TorchCodec，并额外要求一套共享库环境。
Demucs 只需要写出最终的 WAV/FLAC 音轨，因此改用 SoundFile 可以减少运行时依赖，
同时保持本地部署的稳定性和可移植性。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _install_soundfile_save() -> None:
    import numpy as np
    import soundfile
    import torch
    import torchaudio

    def save_with_soundfile(
        uri: str | Path,
        src: torch.Tensor,
        sample_rate: int,
        encoding: str | None = None,
        bits_per_sample: int | None = 16,
        **_: Any,
    ) -> None:
        if not isinstance(uri, (str, Path)):
            raise TypeError("SoundFile output requires a filesystem path")
        data = src.detach().cpu().numpy()
        if data.ndim == 1:
            data = data[:, None]
        elif data.ndim != 2:
            raise ValueError(f"Expected mono or stereo audio, got {data.shape}")
        # TorchAudio 使用“声道数 × 采样数”，SoundFile 使用“采样数 × 声道数”。
        data = np.ascontiguousarray(data.T)
        if bits_per_sample == 24:
            subtype = "PCM_24"
        elif bits_per_sample == 32 and encoding == "PCM_F":
            subtype = "FLOAT"
        elif bits_per_sample == 32:
            subtype = "PCM_32"
        else:
            subtype = "PCM_16"
        soundfile.write(
            str(uri),
            data,
            int(sample_rate),
            subtype=subtype,
        )

    torchaudio.save = save_with_soundfile


def main() -> None:
    _install_soundfile_save()
    from demucs.separate import main as demucs_main

    demucs_main()


if __name__ == "__main__":
    main()
