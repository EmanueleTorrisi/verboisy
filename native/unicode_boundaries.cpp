// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#include "unicode_boundaries.hpp"

namespace verboisy {
bool word(Py_UCS4 character) {
    if (character < 128) {
        const Py_UCS4 lower = character | 0x20u;
        return character == '_' || (character >= '0' && character <= '9') ||
               (lower >= 'a' && lower <= 'z');
    }
    return Py_UNICODE_ISALNUM(character);
}

bool numeric_prefix(Py_UCS4 character) {
    return character == '.' || character == ',' || character == '+' ||
           character == '-' || character == 0x2212;
}

}  // namespace verboisy
