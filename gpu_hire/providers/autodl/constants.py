"""AutoDL constants: GPU names, image UUIDs, regions, CUDA versions."""

# GPU names returned by gpu_stock API (elastic deployment)
KNOWN_GPU_NAMES = [
    "RTX 4090", "RTX 4090D", "RTX 3090", "RTX 3080 Ti", "RTX 3080",
    "RTX 2080 Ti", "A100-PCIE-40GB", "A800-80GB-NVLink",
    "H800", "H20-NVLink", "L20", "V100-32GB", "V100-SXM2-32GB",
    "RTX 5090", "RTX PRO 6000", "vGPU-32GB", "vGPU-48GB",
    "vGPU-48GB-350W", "vGPU-48GB-425W",
]

# Pro instance spec UUID mapping — covers all spec UUIDs + common aliases
# Key = any name the user might pass, Value = spec_uuid for create_instance API
GPU_SPEC_UUIDS: dict[str, str] = {
    # H800
    "H800": "h800",
    "H800-80G": "h800",
    # RTX 4090 (dual 24G = 48G)
    "RTX 4090": "v-48g",
    "RTX 4090-24G": "v-48g",
    "vGPU-48GB": "v-48g",
    # PRO 6000
    "RTX PRO 6000": "pro6000-p",
    "PRO6000-96G": "pro6000-p",
    # RTX 4080S
    "RTX 4080S": "v-32g-p",
    "RTX 4080S-32G": "v-32g-p",
    "vGPU-32GB": "v-32g-p",
    # RTX 3090 (dual 24G = 48G, 350W)
    "RTX 3090": "v-48g-350w",
    "RTX 3090-48G": "v-48g-350w",
    "vGPU-48GB-350W": "v-48g-350w",
    # RTX 5090
    "RTX 5090": "5090-p",
    "RTX 5090-32G": "5090-p",
}

# Reverse: spec_uuid → canonical display name
GPU_SPEC_DISPLAY: dict[str, str] = {
    "h800": "H800-80G",
    "v-48g": "RTX 4090",
    "pro6000-p": "RTX PRO 6000",
    "v-32g-p": "RTX 4080S-32G",
    "v-48g-350w": "RTX 3090",
    "5090-p": "RTX 5090",
}

BASE_IMAGE_UUIDS = {
    "pytorch-cuda11.1": "base-image-12be412037",
    "pytorch-cuda11.3": "base-image-u9r24vthlk",
    "pytorch-cuda11.8": "base-image-l2t43iu6uk",
    "tensorflow-cuda11.2": "base-image-0gxqmciyth",
    "tensorflow-cuda11.4": "base-image-4bpg0tt88l",
    "miniconda-cuda11.6": "base-image-mbr2n4urrc",
    "tensorrt-cuda11.8": "base-image-l2843iu23k",
}

REGIONS = [
    "westDC2", "westDC3",
    "beijingDC1", "beijingDC2", "beijingDC3", "beijingDC4",
    "neimengDC1", "neimengDC3",
    "foshanDC1", "chongqingDC1", "yangzhouDC1",
]

CUDA_VERSIONS = {
    "11.1": 111, "11.3": 113, "11.8": 118,
    "12.0": 120, "12.1": 121, "12.2": 122,
}
