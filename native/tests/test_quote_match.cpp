// Copyright (c) 2026 Emanuele Torrisi.
// See LICENSE for applicable terms.

#include "test_support.hpp"

namespace verboisy::tests {
int test_quote_match() {
    struct Case {
        const char32_t* text;
        const char32_t* quote;
        bool numeric;
        bool expected;
        const char* label;
    };
    const Case cases[] = {
        {U"", U"", false, false, "Empty quote"},
        {U"", U"cat", false, false, "Empty input"},
        {U"cat", U"cat", false, true, "Whole input"},
        {U"a cat!", U"cat", false, true, "Separated word"},
        {U"cats", U"cat", false, false, "Word suffix"},
        {U"bobcat", U"cat", false, false, "Word prefix"},
        {U"_cat", U"cat", false, false, "Underscore prefix"},
        {U"cat_", U"cat", false, false, "Underscore suffix"},
        {U"Cat", U"cat", false, false, "Case is significant"},
        {U"a.c", U"a.c", false, true, "Regex punctuation is literal"},
        {U"abc", U"a.c", false, false, "No regex wildcard"},
        {U"[cat]", U"[cat]", false, true, "Literal brackets"},
        {U"écat", U"cat", false, false, "Latin Unicode boundary"},
        {U"猫cat", U"cat", false, false, "CJK Unicode boundary"},
        {U"catα", U"cat", false, false, "Greek Unicode boundary"},
        {U"cat²", U"cat", false, false, "Numeric word suffix"},
        {U"🐕cat", U"cat", false, true, "Astral separator"},
        {U"𐐀cat", U"cat", false, false, "Astral word prefix"},
        {U"cat́", U"cat", false, true, "Combining mark is not a word boundary blocker"},
        {U"é", U"e", false, false, "No Unicode normalization"},
        {U"12", U"12", true, true, "Whole number"},
        {U"112", U"12", true, false, "Digit prefix"},
        {U"12kg", U"12", true, false, "Unit suffix"},
        {U"+12", U"12", true, false, "Plus prefix"},
        {U"-12", U"12", true, false, "Minus prefix"},
        {U"−12", U"12", true, false, "Unicode minus prefix"},
        {U".12", U"12", true, false, "Decimal prefix"},
        {U",12", U"12", true, false, "Comma prefix"},
        {U"12.5", U"12", true, false, "Decimal tail"},
        {U"12,٥", U"12", true, false, "Unicode decimal tail"},
        {U"12.²", U"12", true, true, "Superscript is not a decimal digit"},
        {U"12.", U"12", true, true, "Sentence period"},
        {U"12, cat", U"12", true, true, "Separated comma"},
        {U"+12; 12", U"12", true, true, "Later valid numeric occurrence"},
        {U"catfish; cat", U"cat", false, true, "Later valid text occurrence"},
        {U"++++4", U"+4", true, false, "Forbidden overlapping numeric starts"},
        {U"!!!", U"!!", false, true, "Overlapping punctuation"},
        {U"+12", U"12", false, true, "Text does not apply numeric prefixes"},
    };
    int checks = 0;
    for (const auto& item : cases) {
        check_match(item.text, item.quote, item.numeric, item.expected, item.label);
        ++checks;
    }
    // Explicit lengths retain embedded NULs; surrogate inputs never pass through
    // UTF-8, matching the production CPython Unicode contract.
    check_match(std::u32string{U'c', U'a', U't', 0, U'x'}, U"cat", false, true, "NUL separator");
    check_match(std::u32string{0xd800, U'c', U'a', U't'}, U"cat", false, true, "Surrogate separator");
    check_match(std::u32string{U'x', 0, U'y'}, std::u32string{0}, false, false, "NUL inside word");
    checks += 3;
    const std::u32string repeated(20000, U'a');
    const std::u32string literal(10000, U'a');
    check_match(repeated, literal, false, false, "Long word has no eligible literal boundary");
    check_match(repeated + U"; " + literal, literal, false, true, "Long later valid literal");
    checks += 2;
    // Repeated execution must not retain positions or results from earlier calls.
    for (int iteration = 0; iteration < 100; ++iteration) {
        check_match(U"catfish", U"cat", false, false, "Repeated negative call");
        check_match(U"cat", U"cat", false, true, "Repeated positive call");
        checks += 2;
    }
    return checks;
}
}  // namespace verboisy::tests
