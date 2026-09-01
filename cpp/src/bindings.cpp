/*
 * HADIN-COMBAT – bindings.cpp
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * pybind11 module that exposes the C++ core (hadin_core) to Python:
 *   - hadin_core.PoseEstimator
 *   - hadin_core.StyleEncoder
 *   - hadin_core.OpponentGenerator
 *   - hadin_core.CoEvolution
 *   - hadin_core.Keypoint / hadin_core.SkeletonLayout
 *
 * Version: 1.0.0
 */
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <string>
#include <vector>

#include "CoEvolution.hpp"
#include "OpponentGenerator.hpp"
#include "PoseEstimator.hpp"
#include "StyleEncoder.hpp"

namespace py = pybind11;
using namespace hadin;

PYBIND11_MODULE(hadin_core, m) {
    m.doc() = "HADIN-COMBAT core AI inference (ONNX Runtime). "
              "Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh.";

    // ---- Version / copyright ------------------------------------------------
    m.attr("__version__") = "1.0.0";
    m.attr("__copyright__") =
        "Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh. All rights reserved.";

    // ---- Skeleton layout -----------------------------------------------------
    py::enum_<SkeletonLayout>(m, "SkeletonLayout")
        .value("COCO_17", SkeletonLayout::COCO_17)
        .value("BODY_18", SkeletonLayout::BODY_18);

    // ---- Keypoint / PoseResult ----------------------------------------------
    py::class_<Keypoint>(m, "Keypoint")
        .def(py::init<>())
        .def_readwrite("x", &Keypoint::x)
        .def_readwrite("y", &Keypoint::y)
        .def_readwrite("score", &Keypoint::score);

    py::class_<PoseResult>(m, "PoseResult")
        .def(py::init<>())
        .def_readwrite("keypoints", &PoseResult::keypoints)
        .def_readwrite("layout", &PoseResult::layout)
        .def_readwrite("inference_ms", &PoseResult::inference_ms);

    // ---- PoseEstimator --------------------------------------------------------
    py::class_<PoseEstimator>(m, "PoseEstimator")
        .def(py::init<std::string, SkeletonLayout>(),
             py::arg("model_path"),
             py::arg("layout") = SkeletonLayout::COCO_17)
        .def("is_ready", &PoseEstimator::is_ready)
        .def("infer",
             [](PoseEstimator& self, py::array_t<float, py::array::c_style | py::array::forcecast> rgb,
                int height, int width) {
                 auto buf = rgb.request();
                 return self.infer(static_cast<const float*>(buf.ptr), height, width);
             },
             py::arg("rgb_float"), py::arg("height"), py::arg("width"));

    // ---- StyleEncoding / StyleEncoder -----------------------------------------
    py::class_<StyleEncoding>(m, "StyleEncoding")
        .def(py::init<>())
        .def_readwrite("latent", &StyleEncoding::latent)
        .def_readwrite("tags", &StyleEncoding::tags);

    py::class_<StyleEncoder>(m, "StyleEncoder")
        .def(py::init<std::string, std::size_t>(), py::arg("model_path"),
             py::arg("latent_dim") = 64)
        .def("is_ready", &StyleEncoder::is_ready)
        .def("encode", &StyleEncoder::encode);

    // ---- OpponentPose / OpponentGenerator -------------------------------------
    py::class_<OpponentPose>(m, "OpponentPose")
        .def(py::init<>())
        .def_readwrite("pose", &OpponentPose::pose)
        .def_readwrite("difficulty", &OpponentPose::difficulty)
        .def_readwrite("latent", &OpponentPose::latent);

    py::class_<OpponentGenerator>(m, "OpponentGenerator")
        .def(py::init<std::string, std::size_t, std::size_t>(),
             py::arg("model_path"), py::arg("num_keypoints") = 17,
             py::arg("latent_dim") = 64)
        .def("is_ready", &OpponentGenerator::is_ready)
        .def("generate", &OpponentGenerator::generate);

    // ---- AthleteProfile / CoEvolution ------------------------------------------
    py::class_<AthleteProfile>(m, "AthleteProfile")
        .def(py::init<>())
        .def_readwrite("athlete_id", &AthleteProfile::athlete_id)
        .def_readwrite("total_sessions", &AthleteProfile::total_sessions)
        .def_readwrite("total_rounds", &AthleteProfile::total_rounds)
        .def_readwrite("win_rate", &AthleteProfile::win_rate)
        .def_readwrite("avg_response_ms", &AthleteProfile::avg_response_ms)
        .def_readwrite("progress_score", &AthleteProfile::progress_score);

    py::class_<CoEvolution>(m, "CoEvolution")
        .def(py::init<std::string>(), py::arg("model_path"))
        .def("is_ready", &CoEvolution::is_ready)
        .def("step", &CoEvolution::step);
}
