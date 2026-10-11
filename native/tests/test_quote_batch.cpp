// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#include "test_support.hpp"
#include "../quote_batch.hpp"

namespace verboisy::tests {
static void expect_error(PyObject* input, PyObject* error, const char* label) {
    PyObject* result = match_quote_batch(input);
    const bool rejected = !result && PyErr_ExceptionMatches(error);
    Py_XDECREF(result);
    PyErr_Clear();
    require(rejected, label);
}

int test_quote_batch() {
    Object empty(PyList_New(0));
    Object empty_output(match_quote_batch(empty.get()));
    require(PyList_GET_SIZE(empty_output.get()) == 0, "Empty batch changed length");
    Object inputs(Py_BuildValue("[(ssO)(ssO)(ssO)]", "cat", "cat", Py_False,
                               "cats", "cat", Py_False, "-12", "12", Py_True));
    Object output(match_quote_batch(inputs.get()));
    require(PyList_GET_SIZE(output.get()) == 3, "Batch changed length");
    require(PyList_GET_ITEM(output.get(), 0) == Py_True, "Positive batch match");
    require(PyList_GET_ITEM(output.get(), 1) == Py_False, "Negative batch word boundary");
    require(PyList_GET_ITEM(output.get(), 2) == Py_False, "Negative batch numeric boundary");
    Object tuple(PyList_AsTuple(inputs.get()));
    Object tuple_output(match_quote_batch(tuple.get()));
    require(PyObject_RichCompareBool(output.get(), tuple_output.get(), Py_EQ) == 1,
            "List and tuple batch outputs differ");
    expect_error(Py_None, PyExc_TypeError, "Non-container batch accepted");
    Object malformed(Py_BuildValue("[(ssO)(s)]", "cat", "cat", Py_False, "bad"));
    expect_error(malformed.get(), PyExc_TypeError, "Partially valid batch accepted");
    Object wrong_flag(Py_BuildValue("[(ssi)]", "cat", "cat", 1));
    expect_error(wrong_flag.get(), PyExc_TypeError, "Non-Boolean numeric flag accepted");
    Object too_large(PyList_New(max_quote_batch + 1));
    expect_error(too_large.get(), PyExc_ValueError, "Oversized batch accepted");
    Object maximum(PyList_New(max_quote_batch));
    for (Py_ssize_t index = 0; index < max_quote_batch; ++index) {
        PyObject* item = PyList_GET_ITEM(inputs.get(), 0);
        Py_INCREF(item);
        PyList_SET_ITEM(maximum.get(), index, item);
    }
    Object maximum_output(match_quote_batch(maximum.get()));
    require(PyList_GET_SIZE(maximum_output.get()) == max_quote_batch, "Maximum batch rejected");
    for (Py_ssize_t index = 0; index < max_quote_batch; ++index) {
        require(PyList_GET_ITEM(maximum_output.get(), index) == Py_True,
                "Maximum batch lost a matching result");
    }
    return 11 + static_cast<int>(max_quote_batch);
}
}  // namespace verboisy::tests
