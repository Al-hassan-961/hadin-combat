/*
 * HADIN-COMBAT – CoEvolution.hpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Co-evolution engine: tracks long-term athlete statistics and adjusts the
 * opponent generator's adaptation pressure so that both the human and the AI
 * keep improving across sessions.
 */
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "onnxruntime_cxx_api.h"

namespace hadin {

/** Cumulative statistics persisted for a single athlete. */
struct AthleteProfile {
    std::string athlete_id;
    std::size_t total_sessions = 0;
    std::size_t total_rounds = 0;
    float win_rate = 0.5f;
    float avg_response_ms = 0.0f;
    float progress_score = 0.0f;  // 0..1 improvement trend
};

class CoEvolution {
public:
    explicit CoEvolution(std::string model_path);
    ~CoEvolution();

    CoEvolution(const CoEvolution&) = delete;
    CoEvolution& operator=(const CoEvolution&) = delete;
    CoEvolution(CoEvolution&&) noexcept;
    CoEvolution& operator=(CoEvolution&&) noexcept;

    bool is_ready() const noexcept;

    /**
     * Given an athlete's history, return the next recommended difficulty
     * and the expected opponent latent adjustment.
     * @return (next_difficulty, latent_delta) or std::nullopt on failure.
     */
    std::optional<std::pair<float, std::vector<float>>> step(
        const AthleteProfile& profile,
        const std::vector<float>& current_latent) const;

    static const char* name() noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hadin
