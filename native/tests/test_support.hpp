// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#pragma once

#include "../quote_match.hpp"
#include <stdexcept>
#include <string>

namespace verboisy::tests {
// Test objects own one reference while the calling Python thread holds the GIL.
// This keeps failed assertions from leaking their temporary Unicode inputs.
class Object {
public:
    explicit Object(PyObject* value) : value_(value) {
        if (!value_) throw std::runtime_error("Python allocation failed");
    }
    ~Object() { Py_DECREF(value_); }
    Object(const Object&) = delete;
    Object& operator=(const Object&) = delete;
    PyObject* get() const { return value_; }
private:
    PyObject* value_;
};

inline void require(bool condition, const char* label) {
    if (!condition) throw std::runtime_error(label);
}

inline void check_match(const std::u32string& text, const std::u32string& quote,
                        bool numeric, bool expected, const char* label) {
    Object input(PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, text.data(), text.size()));
    Object literal(PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, quote.data(), quote.size()));
    Object result(match_quote(input.get(), literal.get(), numeric));
    require(PyBool_Check(result.get()), "Matcher did not return a Python Boolean");
    require((result.get() == Py_True) == expected, label);
}

int test_quote_match();
int test_quote_batch();
int test_unicode_boundaries();
}  // namespace verboisy::tests
