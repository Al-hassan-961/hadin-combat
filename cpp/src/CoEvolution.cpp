/*
 * HADIN-COMBAT – CoEvolution.cpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 */
#include "CoEvolution.hpp"

#include <algorithm>
#include <stdexcept>

#include "onnxruntime_cxx_api.h"

namespace hadin {

struct CoEvolution::Impl {
    Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "hadin_evo"};
    Ort::SessionOptions opts;
    Ort::Session session{nullptr};
    bool ready = false;

    Impl() {
        opts.SetIntraOpNumThreads(2);
        opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    }
};

CoEvolution::CoEvolution(std::string model_path)
    : impl_(std::make_unique<Impl>()) {
    try {
        impl_->session = Ort::Session(impl_->env, model_path.c_str(), impl_->opts);
        impl_->ready = true;
    } catch (const std::exception&) {
        impl_->ready = false;
    }
}

CoEvolution::CoEvolution(CoEvolution&&) noexcept = default;
CoEvolution& CoEvolution::operator=(CoEvolution&&) noexcept = default;
CoEvolution::~CoEvolution() = default;

bool CoEvolution::is_ready() const noexcept { return impl_ && impl_->ready; }

const char* CoEvolution::name() noexcept { return "coevolution"; }

std::optional<std::pair<float, std::vector<float>>> CoEvolution::step(
    const AthleteProfile& profile, const std::vector<float>& current_latent) const {
    if (!is_ready() || current_latent.empty()) {
        return std::nullopt;
    }

    try {
        // Feature vector: [win_rate, progress, avg_response, sessions, latent...]
        std::vector<float> input;
        input.push_back(profile.win_rate);
        input.push_back(profile.progress_score);
        input.push_back(profile.avg_response_ms / 1000.0f);
        input.push_back(static_cast<float>(profile.total_sessions));
        input.insert(input.end(), current_latent.begin(), current_latent.end());

        std::vector<int64_t> shape{1, static_cast<int64_t>(input.size())};
        Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,
                                                         OrtMemTypeDefault);
        Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
            mem, input.data(), input.size(), shape.data(), shape.size());

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
        for (auto s : shape_out) total *= static_cast<std::size_t>(s);

        if (total < 1) {
            return std::nullopt;
        }

        const float next_difficulty = std::min(1.0f, std::max(0.0f, data[0]));
        std::vector<float> delta;
        if (total > 1) {
            delta.assign(data + 1, data + total);
        }
        return std::make_pair(next_difficulty, std::move(delta));
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

}  // namespace hadin
