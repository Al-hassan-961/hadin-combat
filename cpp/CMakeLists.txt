# ---------------------------------------------------------------------------
# HADIN-COMBAT – C++ core build
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# ---------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.16)

project(hadin_core
    VERSION 1.0.0
    DESCRIPTION "HADIN-COMBAT core AI inference library"
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# ---- ARM optimization flags (Termux / mobile) ------------------------------
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
    add_compile_options(-O3 -funroll-loops -flto)
    add_compile_options(-march=armv8-a+fp16)
    message(STATUS "HADIN: detected ARM64 target - applying mobile optimizations")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^arm")
    add_compile_options(-O3 -marm -mfpu=neon)
    message(STATUS "HADIN: detected ARM32 target - enabling NEON")
else()
    add_compile_options(-O3)
endif()

add_compile_options(-fPIC)

# ---- Dependencies ----------------------------------------------------------
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter Development.Module)

find_package(onnxruntime QUIET)
if(NOT onnxruntime_FOUND)
    message(WARNING
        "HADIN: ONNX Runtime not found via find_package. "
        "Try: pip install onnxruntime && set ONNXRUNTIME_ROOT to its location.")
    # Allow discovery through ONNXRUNTIME_ROOT hint
    set(ONNXRUNTIME_ROOT "" CACHE PATH "Path to onnxruntime include/lib dirs")
    find_library(ONNXRUNTIME_LIB
        NAMES onnxruntime
        HINTS ${ONNXRUNTIME_ROOT}/lib /usr/local/lib ${Python3_SITEARCH}/onnxruntime/capi)
    find_path(ONNXRUNTIME_INCLUDE_DIR
        NAMES onnxruntime_cxx_api.h onnxruntime_c_api.h
        HINTS ${ONNXRUNTIME_ROOT}/include /usr/include/onnxruntime)
    if(ONNXRUNTIME_LIB AND ONNXRUNTIME_INCLUDE_DIR)
        add_library(onnxruntime::onnxruntime SHARED IMPORTED)
        set_target_properties(onnxruntime::onnxruntime PROPERTIES
            IMPORTED_LOCATION ${ONNXRUNTIME_LIB})
        set(ONNXRUNTIME_INCLUDE_DIRS ${ONNXRUNTIME_INCLUDE_DIR})
    else()
        message(FATAL_ERROR "HADIN: ONNX Runtime library not found. Install it and rerun cmake.")
    endif()
else()
    set(ONNXRUNTIME_INCLUDE_DIRS onnxruntime)
endif()

find_package(pybind11 2.9 REQUIRED)

# ---- Library -----------------------------------------------------------------
add_library(hadin_core SHARED
    src/PoseEstimator.cpp
    src/StyleEncoder.cpp
    src/OpponentGenerator.cpp
    src/CoEvolution.cpp
    src/bindings.cpp)

target_include_directories(hadin_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${ONNXRUNTIME_INCLUDE_DIRS})

target_link_libraries(hadin_core PRIVATE
    onnxruntime::onnxruntime
    pybind11::module)

target_include_directories(hadin_core PRIVATE
    ${Python3_INCLUDE_DIRS})

set_target_properties(hadin_core PROPERTIES
    OUTPUT_NAME hadin_core
    POSITION_INDEPENDENT_CODE ON)

# Install so Python can import it (copy into python-backend/app)
install(TARGETS hadin_core LIBRARY DESTINATION lib)
add_custom_command(TARGET hadin_core POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy
        $<TARGET_FILE:hadin_core>
        ${CMAKE_CURRENT_SOURCE_DIR}/../python-backend/app/hadin_core${CMAKE_SHARED_LIBRARY_SUFFIX}
    COMMENT "HADIN: copied hadin_core to python-backend/app")

message(STATUS "HADIN: C++ core configured - building ${CMAKE_BUILD_TYPE}")
