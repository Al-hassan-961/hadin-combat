/*
 * HADIN-COMBAT – OpponentGenerator.cpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 */
#include "OpponentGenerator.hpp"

#include <stdexcept>

#include "onnxruntime_cxx_api.h"

namespace hadin {

struct OpponentGenerator::Impl {
    Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "hadin_opp"};
    Ort::SessionOptions opts;
    Ort::Session session{nullptr};
    bool ready = false;
    std::size_t num_keypoints = 17;
    std::size_t latent_dim = 64;

    Impl() {
        opts.SetIntraOpNumThreads(2);
        opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    }
};

OpponentGenerator::OpponentGenerator(std::string model_path, std::size_t num_keypoints,
                                     std::size_t latent_dim)
    : impl_(std::make_unique<Impl>()) {
    impl_->num_keypoints = num_keypoints;
    impl_->latent_dim = latent_dim;
    try {
        impl_->session = Ort::Session(impl_->env, model_path.c_str(), impl_->opts);
        impl_->ready = true;
    } catch (const std::exception&) {
        impl_->ready = false;
    }
}

OpponentGenerator::OpponentGenerator(OpponentGenerator&&) noexcept = default;
OpponentGenerator& OpponentGenerator::operator=(OpponentGenerator&&) noexcept = default;
OpponentGenerator::~OpponentGenerator() = default;

bool OpponentGenerator::is_ready() const noexcept { return impl_ && impl_->ready; }

const char* OpponentGenerator::name() noexcept { return "opponent_generator"; }

std::optional<OpponentPose> OpponentGenerator::generate(const std::vector<float>& style_latent,
                                                        float difficulty) const {
    if (!is_ready() || style_latent.size() != impl_->latent_dim) {
        return std::nullopt;
    }
    const float d = std::min(1.0f, std::max(0.0f, difficulty));

    try {
        std::vector<int64_t> latent_shape{1, static_cast<int64_t>(impl_->latent_dim)};
        std::vector<float> latent = style_latent;
        latent.push_back(d);  // difficulty appended as conditioning

        std::vector<int64_t> cond_shape{1, static_cast<int64_t>(impl_->latent_dim + 1)};

        Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,
                                                         OrtMemTypeDefault);
        Ort::Value latent_tensor = Ort::Value::CreateTensor<float>(
            mem, latent.data(), latent.size(), cond_shape.data(), cond_shape.size());

        const char* in_name = "input";
        const char* out_name = "output";
        auto outputs =
            impl_->session.Run(Ort::RunOptions{nullptr}, &in_name, &latent_tensor, 1,
                               &out_name, 1);
        if (outputs.empty() || !outputs[0].IsTensor()) {
            return std::nullopt;
        }

        const float* data = outputs[0].GetTensorData<float>();
        const auto shape_out = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
        std::size_t total = 1;
        for (auto s : shape_out) total *= static_cast<std::size_t>(s);

        OpponentPose op;
        op.difficulty = d;
        op.latent = style_latent;
        op.pose.assign(data, data + std::min(total, impl_->num_keypoints * 2));
        return op;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

}  // namespace hadin
