// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#include "test_support.hpp"
#include "../unicode_boundaries.hpp"

namespace verboisy::tests {
int test_unicode_boundaries() {
    // Expectations distinguish Unicode alphanumeric characters from combining
    // marks and decimal digits from broader numeric characters used as words.
    const Py_UCS4 words[] = {'A', 'z', '0', '_', 0x00e9, 0x03b1, 0x4e2d,
                            0x0663, 0x00b2, 0x2163, 0x10400};
    const Py_UCS4 separators[] = {0, ' ', '.', ',', '+', '-', 0x2212,
                                 0x0301, 0x200b, 0x1f415, 0xd800, 0x10ffff};
    int checks = 0;
    for (auto value : words) {
        require(word(value), "Expected Unicode word character");
        ++checks;
    }
    for (auto value : separators) {
        require(!word(value), "Separator incorrectly classified as word character");
        ++checks;
    }
    for (auto value : {'.', ',', '+', '-'}) {
        require(numeric_prefix(value), "ASCII numeric prefix was accepted as a boundary");
        ++checks;
    }
    require(numeric_prefix(0x2212), "Unicode minus must block a numeric start");
    ++checks;
    for (Py_UCS4 value : {0u, 0x20u, 0x41u, 0x5fu, 0x0663u, 0x2013u, 0x1f415u}) {
        require(!numeric_prefix(value), "Unrelated character became a numeric prefix");
        ++checks;
    }
    return checks;
}
}  // namespace verboisy::tests
