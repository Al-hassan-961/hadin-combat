/*
 * HADIN-COMBAT – StyleEncoder.cpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 */
#include "StyleEncoder.hpp"

#include <algorithm>
#include <stdexcept>

#include "onnxruntime_cxx_api.h"

namespace hadin {

struct StyleEncoder::Impl {
    Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "hadin_style"};
    Ort::SessionOptions opts;
    Ort::Session session{nullptr};
    bool ready = false;
    std::size_t latent_dim = 64;

    Impl() {
        opts.SetIntraOpNumThreads(2);
        opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    }
};

StyleEncoder::StyleEncoder(std::string model_path, std::size_t latent_dim)
    : impl_(std::make_unique<Impl>()) {
    impl_->latent_dim = latent_dim;
    try {
        impl_->session = Ort::Session(impl_->env, model_path.c_str(), impl_->opts);
        impl_->ready = true;
    } catch (const std::exception&) {
        impl_->ready = false;
    }
}

StyleEncoder::StyleEncoder(StyleEncoder&&) noexcept = default;
StyleEncoder& StyleEncoder::operator=(StyleEncoder&&) noexcept = default;
StyleEncoder::~StyleEncoder() = default;

bool StyleEncoder::is_ready() const noexcept { return impl_ && impl_->ready; }

const char* StyleEncoder::name() noexcept { return "style_encoder"; }

std::optional<std::vector<StyleEncoding>> StyleEncoder::encode(
    const std::vector<std::vector<float>>& sequences, std::size_t seq_len) const {
    if (!is_ready() || sequences.empty() || seq_len == 0) {
        return std::nullopt;
    }

    const std::size_t num_sequences = sequences.size();
    const std::size_t elem_per_frame =
        sequences[0].size() / seq_len;  // keypoints * 2
    if (elem_per_frame == 0) {
        return std::nullopt;
    }

    try {
        std::vector<int64_t> shape{static_cast<int64_t>(num_sequences),
                                   static_cast<int64_t>(seq_len),
                                   static_cast<int64_t>(elem_per_frame)};
        const std::size_t num_elems =
            num_sequences * seq_len * elem_per_frame;
        std::vector<float> input(num_elems, 0.0f);
        std::size_t offset = 0;
        for (const auto& seq : sequences) {
            for (std::size_t i = 0; i < seq.size() && offset < num_elems; ++i, ++offset) {
                input[offset] = seq[i];
            }
        }

        Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,
                                                         OrtMemTypeDefault);
        Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
            mem, input.data(), num_elems, shape.data(), shape.size());

        const char* in_name = "input";
        const char* out_name = "output";
        auto outputs =
            impl_->session.Run(Ort::RunOptions{nullptr}, &in_name, &input_tensor, 1,
                               &out_name, 1);
        if (outputs.empty() || !outputs[0].IsTensor()) {
            return std::nullopt;
        }

        const float* data = outputs[0].GetTensorData<float>();
        const auto shape_out = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
        std::size_t total = 1;
        for (auto d : shape_out) total *= static_cast<std::size_t>(d);
        std::size_t per_latent = total / num_sequences;
        if (per_latent == 0) {
            return std::nullopt;
        }

        std::vector<StyleEncoding> encodings;
        encodings.reserve(num_sequences);
        for (std::size_t s = 0; s < num_sequences; ++s) {
            StyleEncoding enc;
            enc.latent.assign(data + s * per_latent, data + (s + 1) * per_latent);
            if (enc.latent.size() > impl_->latent_dim) {
                enc.latent.resize(impl_->latent_dim);
            }
            // Heuristic tendency tags based on latent mean/std. Production
            // versions use a small classifier head on the latent.
            const float mean =
                std::accumulate(enc.latent.begin(), enc.latent.end(), 0.0f) /
                static_cast<float>(enc.latent.size());
            enc.tags = mean > 0.0f ? std::vector<std::string>{"aggressive", "fast"}
                                   : std::vector<std::string>{"defensive", "patient"};
            encodings.push_back(std::move(enc));
        }
        return encodings;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

}  // namespace hadin
