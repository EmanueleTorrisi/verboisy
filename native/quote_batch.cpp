// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#include "quote_batch.hpp"
#include "quote_match.hpp"

namespace verboisy {
PyObject* match_quote_batch(PyObject* cases) {
    // Materialize only built-in containers; iterators and arbitrary sequence
    // hooks would introduce uncontrolled Python execution inside this loop.
    if (!PyList_CheckExact(cases) && !PyTuple_CheckExact(cases)) {
        PyErr_SetString(PyExc_TypeError, "Quote batch must be a list or tuple");
        return nullptr;
    }
    const bool is_list = PyList_CheckExact(cases);
    const Py_ssize_t size = is_list ? PyList_GET_SIZE(cases) : PyTuple_GET_SIZE(cases);
    if (size > max_quote_batch) {
        PyErr_SetString(PyExc_ValueError, "Quote batch exceeds 4096 entries");
        return nullptr;
    }
    PyObject* output = PyList_New(size);
    if (!output) return nullptr;
    for (Py_ssize_t index = 0; index < size; ++index) {
        PyObject* item = is_list ? PyList_GET_ITEM(cases, index) : PyTuple_GET_ITEM(cases, index);
        if (!PyTuple_CheckExact(item) || PyTuple_GET_SIZE(item) != 3) {
            PyErr_SetString(PyExc_TypeError, "Quote batch entries must be (text, quote, bool) tuples");
            Py_DECREF(output);
            return nullptr;
        }
        PyObject* text = PyTuple_GET_ITEM(item, 0);
        PyObject* quote = PyTuple_GET_ITEM(item, 1);
        PyObject* numeric = PyTuple_GET_ITEM(item, 2);
        if (!PyUnicode_Check(text) || !PyUnicode_Check(quote) || !PyBool_Check(numeric)) {
            PyErr_SetString(PyExc_TypeError, "Quote batch entries must contain two strings and a bool");
            Py_DECREF(output);
            return nullptr;
        }
        PyObject* result = match_quote(text, quote, numeric == Py_True);
        if (!result) {
            Py_DECREF(output);
            return nullptr;
        }
        // The list owns this new Boolean reference. A later failure destroys
        // the whole list; partially checked evidence is never returned.
        PyList_SET_ITEM(output, index, result);
    }
    return output;
}
}  // namespace verboisy
