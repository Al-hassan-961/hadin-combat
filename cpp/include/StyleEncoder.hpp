/*
 * HADIN-COMBAT – StyleEncoder.hpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Compresses a sequence of pose frames into a fixed-size latent vector that
 * represents the athlete's "Fighting DNA" – a compact style fingerprint.
 */
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "onnxruntime_cxx_api.h"

namespace hadin {

/**
 * StyleEncoding is a fixed-size embedding of an athlete's movement style.
 * Internally it is the bottleneck of a sequence autoencoder.
 */
struct StyleEncoding {
    std::vector<float> latent;  // e.g. 64 floats
    std::vector<std::string> tags;  // human-readable inferred tendencies
};

class StyleEncoder {
public:
    explicit StyleEncoder(std::string model_path, std::size_t latent_dim = 64);
    ~StyleEncoder();

    StyleEncoder(const StyleEncoder&) = delete;
    StyleEncoder& operator=(const StyleEncoder&) = delete;
    StyleEncoder(StyleEncoder&&) noexcept;
    StyleEncoder& operator=(StyleEncoder&&) noexcept;

    bool is_ready() const noexcept;

    /**
     * Encode a batch of pose sequences.
     * @param sequences vector of sequence tensors, each [seq_len, num_keypoints*2].
     * @param seq_len   number of frames per sequence.
     * @return one StyleEncoding per sequence, or std::nullopt on failure.
     */
    std::optional<std::vector<StyleEncoding>> encode(
        const std::vector<std::vector<float>>& sequences, std::size_t seq_len) const;

    static const char* name() noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hadin
