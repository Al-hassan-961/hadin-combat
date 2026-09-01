/*
 * HADIN-COMBAT – PoseEstimator.cpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 */
#include "PoseEstimator.hpp"

#include <chrono>
#include <fstream>
#include <stdexcept>
#include <utility>

#include "onnxruntime_cxx_api.h"

namespace hadin {

namespace {
constexpr std::size_t kMaxKeypoints = 128;

const char* kInputName = "input";
const char* kOutputName = "output";
}  // namespace

struct PoseEstimator::Impl {
    Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "hadin_pose"};
    Ort::SessionOptions opts;
    Ort::Session session{nullptr};
    bool ready = false;
    SkeletonLayout layout = SkeletonLayout::COCO_17;

    std::vector<std::string> input_names;
    std::vector<std::string> output_names;

    Impl() {
        opts.SetIntraOpNumThreads(2);
        opts.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    }
};

PoseEstimator::PoseEstimator(std::string model_path, SkeletonLayout layout)
    : impl_(std::make_unique<Impl>()) {
    impl_->layout = layout;
    std::ifstream probe(model_path, std::ios::binary);
    if (!probe.good()) {
        // Not fatal: the caller checks is_ready() and falls back to MediaPipe.
        return;
    }
    probe.close();

    try {
        impl_->session = Ort::Session(impl_->env, model_path.c_str(), impl_->opts);
        const Ort::AllocatorWithDefaultOptions alloc;

        const size_t in_count = impl_->session.GetInputCount();
        const size_t out_count = impl_->session.GetOutputCount();
        for (size_t i = 0; i < in_count; ++i) {
            auto name = impl_->session.GetInputNameAllocated(i, alloc);
            impl_->input_names.emplace_back(name.get());
        }
        for (size_t i = 0; i < out_count; ++i) {
            auto name = impl_->session.GetOutputNameAllocated(i, alloc);
            impl_->output_names.emplace_back(name.get());
        }
        impl_->ready = true;
    } catch (const std::exception& e) {
        impl_->ready = false;
        // ready stays false; fallback logic handles degradation.
    }
}

PoseEstimator::PoseEstimator(PoseEstimator&&) noexcept = default;
PoseEstimator& PoseEstimator::operator=(PoseEstimator&&) noexcept = default;
PoseEstimator::~PoseEstimator() = default;

bool PoseEstimator::is_ready() const noexcept { return impl_ && impl_->ready; }

const char* PoseEstimator::name() noexcept { return "pose_onnx"; }

std::optional<PoseResult> PoseEstimator::infer(const float* rgb_float, int height,
                                               int width) const {
    if (!is_ready() || rgb_float == nullptr || height <= 0 || width <= 0) {
        return std::nullopt;
    }

    const auto t0 = std::chrono::steady_clock::now();
    try {
        std::vector<int64_t> shape{1, 3, height, width};
        Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(
            OrtArenaAllocator, OrtMemTypeDefault);
        Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
            mem, const_cast<float*>(rgb_float),
            static_cast<size_t>(3) * height * width, shape.data(), shape.size());

        std::array<const char*, 1> input_names{impl_->input_names[0].c_str()};
        std::array<const char*, 1> output_names{impl_->output_names[0].c_str()};

        auto outputs = impl_->session.Run(Ort::RunOptions{nullptr},
                                          input_names.data(), &input_tensor, 1,
                                          output_names.data(), 1);
        if (outputs.empty() || !outputs[0].IsTensor()) {
            return std::nullopt;
        }

        const float* data = outputs[0].GetTensorData<float>();
        const auto shape_out = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
        // Assume [1, N, 3] or [1, 3, N]; N keypoints each (x, y, score).
        std::size_t total = 1;
        for (auto d : shape_out) total *= static_cast<std::size_t>(d);
        std::size_t num_keypoints = std::min(total / 3, kMaxKeypoints);

        PoseResult result;
        result.layout = impl_->layout;
        result.keypoints.reserve(num_keypoints);
        for (std::size_t k = 0; k < num_keypoints; ++k) {
            Keypoint kp;
            kp.x = data[k * 3 + 0];
            kp.y = data[k * 3 + 1];
            kp.score = data[k * 3 + 2];
            result.keypoints.push_back(kp);
        }

        const auto t1 = std::chrono::steady_clock::now();
        result.inference_ms = std::chrono::duration<float, std::milli>(t1 - t0).count();
        return result;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

}  // namespace hadin
