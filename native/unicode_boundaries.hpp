// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

namespace verboisy {
// Classification follows the running interpreter's Unicode tables.
bool word(Py_UCS4 character);
bool numeric_prefix(Py_UCS4 character);
}
