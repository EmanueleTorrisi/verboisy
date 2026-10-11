// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

namespace verboisy {
// Bound temporary output references per call. Each input retains the scalar
// matcher's Unicode/GIL contract; no matching state survives the batch.
constexpr Py_ssize_t max_quote_batch = 4096;
PyObject* match_quote_batch(PyObject* cases);
}
