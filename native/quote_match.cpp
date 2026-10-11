// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

// Literal search and overlap handling belong here; argument parsing belongs in
// the module adapter. No state survives an individual matching call.
#include "quote_match.hpp"
#include "unicode_boundaries.hpp"

namespace verboisy {
PyObject* match_quote(PyObject* text, PyObject* quote, bool numeric) {
#if PY_VERSION_HEX < 0x030C0000
    if (PyUnicode_READY(text) < 0 || PyUnicode_READY(quote) < 0) {
        return nullptr;
    }
#endif
    const Py_ssize_t size = PyUnicode_GET_LENGTH(text);
    const Py_ssize_t length = PyUnicode_GET_LENGTH(quote);
    if (length == 0) {
        Py_RETURN_FALSE;
    }
    const int kind = PyUnicode_KIND(text);
    const void* data = PyUnicode_DATA(text);
    Py_ssize_t start = 0;
    while (start <= size) {
        // CPython supplies its literal search; this extension removes dynamic
        // regex compilation and checks boundaries without Python call overhead.
        const Py_ssize_t position = PyUnicode_Find(text, quote, start, size, 1);
        if (position == -2) {
            return nullptr;
        }
        if (position < 0) {
            Py_RETURN_FALSE;
        }
        const Py_ssize_t end = position + length;
        const Py_UCS4 before = position ? PyUnicode_READ(kind, data, position - 1) : 0;
        const Py_UCS4 after = end < size ? PyUnicode_READ(kind, data, end) : 0;
        const bool left = position && (word(before) || (numeric && numeric_prefix(before)));
        const bool decimal_tail = numeric && end + 1 < size &&
            (after == '.' || after == ',') &&
            Py_UNICODE_ISDECIMAL(PyUnicode_READ(kind, data, end + 1));
        if (!left && !word(after) && !decimal_tail) {
            Py_RETURN_TRUE;
        }
        start = position + 1;
        // Skip starts with forbidden predecessors, preserving overlaps at every
        // eligible boundary. This avoids quadratic repeated searches inside a
        // long run of word characters containing a long repeated literal.
        while (start < size) {
            const Py_UCS4 predecessor = PyUnicode_READ(kind, data, start - 1);
            if (!word(predecessor) && !(numeric && numeric_prefix(predecessor))) {
                break;
            }
            ++start;
        }
    }
    Py_RETURN_FALSE;
}

}  // namespace verboisy
