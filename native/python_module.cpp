// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

// Keep the Python-facing signature and module registration independent of the
// matching algorithm. This adapter validates types before direct Unicode access.
#include "quote_match.hpp"
#include "quote_batch.hpp"

static PyObject* quote_observed(PyObject*, PyObject* args) {
    PyObject *text, *quote;
    int numeric = 0;
    if (!PyArg_ParseTuple(args, "UU|p:quote_observed", &text, &quote, &numeric)) {
        return nullptr;
    }
    return verboisy::match_quote(text, quote, numeric != 0);
}

static PyMethodDef methods[] = {
    {"quote_observed", quote_observed, METH_VARARGS, "Match a literal with verifier boundaries."},
    {"quotes_observed", [](PyObject*, PyObject* cases) -> PyObject* {
        return verboisy::match_quote_batch(cases);
    }, METH_O, "Match up to 4096 (text, quote, bool) tuples in input order."},
    {nullptr, nullptr, 0, nullptr}
};
static PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_verboisy_quote_native", nullptr, -1, methods,
    nullptr, nullptr, nullptr, nullptr
};

PyMODINIT_FUNC PyInit__verboisy_quote_native() {
    return PyModule_Create(&module);
}
