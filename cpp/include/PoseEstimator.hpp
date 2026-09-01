/*
 * HADIN-COMBAT – PoseEstimator.hpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Performs real-time single-person pose estimation via ONNX Runtime.
 * Input:  pre-normalized image tensor [1,3,H,W]
 * Output: keypoints (x, y, confidence) for the HADIN skeleton layout.
 */
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "onnxruntime_cxx_api.h"

namespace hadin {

/** A single 2D keypoint with confidence. */
struct Keypoint {
    float x = 0.0f;
    float y = 0.0f;
    float score = 0.0f;
};

/** Ordering/semantics of keypoints produced by the pose model. */
enum class SkeletonLayout {
    COCO_17 = 0,  // COCO 17-keypoint layout
    BODY_18 = 1,  // 18-point whole-body layout
};

struct PoseResult {
    std::vector<Keypoint> keypoints;  // in model layout order
    SkeletonLayout layout = SkeletonLayout::COCO_17;
    float inference_ms = 0.0f;
};

class PoseEstimator {
public:
    explicit PoseEstimator(std::string model_path,
                           SkeletonLayout layout = SkeletonLayout::COCO_17);
    ~PoseEstimator();

    // Non-copyable (owns an ONNX session).
    PoseEstimator(const PoseEstimator&) = delete;
    PoseEstimator& operator=(const PoseEstimator&) = delete;
    PoseEstimator(PoseEstimator&&) noexcept;
    PoseEstimator& operator=(PoseEstimator&&) noexcept;

    /** Returns false if the model failed to load (caller should fall back). */
    bool is_ready() const noexcept;

    /** Run inference. Returns std::nullopt on failure. */
    std::optional<PoseResult> infer(const float* rgb_float, int height, int width) const;

    /** Human-readable name, e.g. "pose_onnx". */
    static const char* name() noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hadin
