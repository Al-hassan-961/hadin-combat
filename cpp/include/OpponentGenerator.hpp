/*
 * HADIN-COMBAT – OpponentGenerator.hpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Turns an athlete's Fighting-DNA style vector into a concrete opponent
 * target pose, calibrated by difficulty. Uses a diffusion-style generator
 * exported to ONNX.
 */
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "onnxruntime_cxx_api.h"

namespace hadin {

struct OpponentPose {
    std::vector<float> pose;      // [num_keypoints*2] normalized (x, y)
    float difficulty = 0.5f;      // 0..1
    std::vector<float> latent;    // the latent used to produce this pose
};

class OpponentGenerator {
public:
    explicit OpponentGenerator(std::string model_path,
                               std::size_t num_keypoints = 17,
                               std::size_t latent_dim = 64);
    ~OpponentGenerator();

    OpponentGenerator(const OpponentGenerator&) = delete;
    OpponentGenerator& operator=(const OpponentGenerator&) = delete;
    OpponentGenerator(OpponentGenerator&&) noexcept;
    OpponentGenerator& operator=(OpponentGenerator&&) noexcept;

    bool is_ready() const noexcept;

    /**
     * Generate one opponent pose.
     * @param style_latent the athlete's Fighting-DNA vector (size latent_dim).
     * @param difficulty   0..1 adaptation pressure.
     * @return an OpponentPose, or std::nullopt on failure.
     */
    std::optional<OpponentPose> generate(const std::vector<float>& style_latent,
                                         float difficulty) const;

    static const char* name() noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hadin
