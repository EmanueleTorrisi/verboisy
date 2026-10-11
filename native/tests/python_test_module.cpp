// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

// The test-only module lets the selected interpreter own initialization and the
// GIL. It links the real production implementation, with no libpython embedding
// requirement and no additional test framework.
#include "test_support.hpp"
#include <cstring>

static PyObject* run_suite(PyObject*, PyObject* args) {
    const char* suite;
    if (!PyArg_ParseTuple(args, "s:run_suite", &suite)) return nullptr;
    try {
        int checks;
        if (std::strcmp(suite, "quote_match") == 0) {
            checks = verboisy::tests::test_quote_match();
        } else if (std::strcmp(suite, "unicode_boundaries") == 0) {
            checks = verboisy::tests::test_unicode_boundaries();
        } else if (std::strcmp(suite, "quote_batch") == 0) {
            checks = verboisy::tests::test_quote_batch();
        } else {
            PyErr_SetString(PyExc_ValueError, "Unknown native test suite");
            return nullptr;
        }
        return PyLong_FromLong(checks);
    } catch (const std::exception& error) {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_AssertionError, error.what());
        return nullptr;
    } catch (...) {
        PyErr_SetString(PyExc_RuntimeError, "Unexpected native test exception");
        return nullptr;
    }
}

static PyMethodDef methods[] = {
    {"run_suite", run_suite, METH_VARARGS, "Execute direct C++ assertions; return the check count."},
    {nullptr, nullptr, 0, nullptr}
};
static PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_verboisy_quote_native_tests", nullptr, -1, methods,
    nullptr, nullptr, nullptr, nullptr
};

PyMODINIT_FUNC PyInit__verboisy_quote_native_tests() {
    return PyModule_Create(&module);
}
