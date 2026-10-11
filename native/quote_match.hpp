// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

namespace verboisy {
// Inputs must be Python Unicode objects and the caller must hold the GIL.
// Return a new Boolean reference, or nullptr with a Python exception set.
PyObject* match_quote(PyObject* text, PyObject* quote, bool numeric);
}
