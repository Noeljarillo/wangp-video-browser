# Models used by the analysis add-on

All weights are open, run locally, and are fetched once into `app/.cache/models/`
(`app/analysis/env/bin/python app/analysis/faces.py --download`). Nothing is downloaded at runtime (C3).

## P3.2 Faces and people (`app/analysis/faces.py`)

| Model | Use | Licence | Source |
| --- | --- | --- | --- |
| YuNet `face_detection_yunet_2023mar.onnx` | face boxes + landmarks (OpenCV `FaceDetectorYN`, CPU) | MIT | opencv_zoo `models/face_detection_yunet` |
| SFace `face_recognition_sface_2021dec.onnx` | 128-d identity embedding of the aligned face (`FaceRecognizerSF`, CPU) | Apache-2.0 | opencv_zoo `models/face_recognition_sface` |
| Faster R-CNN MobileNetV3-Large FPN (COCO) `fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth` | person boxes (torchvision, CUDA fp16 autocast or CPU) | BSD-3-Clause (torchvision) | download.pytorch.org/models |
| DINOv2-small `facebook/dinov2-small` | 384-d crop embedding of each person, for stylised / anime / non-human characters | Apache-2.0 | huggingface.co/facebook/dinov2-small |

InsightFace pretrained weights are deliberately **not** used: they are licensed for non-commercial
research only. SFace is weaker than ArcFace-R100 on hard real-face benchmarks, which is an acceptable
trade for a permissive licence; DINOv2 crops cover faces SFace can't embed (stylised characters).

## P4.1 Semantic search / P4.2 auto-tags (`app/analysis/semantic.py`, `app/analysis/tags.py`)

| Model | Use | Licence | Source |
| --- | --- | --- | --- |
| SigLIP base `google/siglip-base-patch16-224` | 768-d image embedding per sampled frame (CUDA fp16, CPU fp32 fallback) and text-query embedding; zero-shot tags | Apache-2.0 | huggingface.co/google/siglip-base-patch16-224 |

Fetched once into `app/.cache/models/` on the first `semantic` job (`huggingface_hub.snapshot_download`, weights + `tokenizer.json`; the text side uses the `tokenizers` fast tokenizer, so `sentencepiece` is not needed). Camera motion (P4.2) uses OpenCV Farneback optical flow - no weights.
