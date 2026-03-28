"""AutoDL constants: GPU names, image UUIDs, regions, CUDA versions."""

KNOWN_GPU_NAMES = [
    "RTX 4090", "RTX 3090", "RTX 3080 Ti",
    "A100 SXM4", "A800", "H800",
    "L20", "V100", "RTX A4000",
]

GPU_SPEC_UUIDS = {
    "H800-80G": "h800",
    "RTX 4090-24G": "v-48g",
    "PRO6000-96G": "pro6000-p",
    "RTX 4080S-32G": "v-32g-p",
    "RTX 3090-48G": "v-48g-350w",
    "RTX 5090-32G": "5090-p",
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
