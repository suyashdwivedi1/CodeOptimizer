#include <stdio.h>
#include <stdint.h>
static uint64_t mulmod(uint64_t a, uint64_t b, uint64_t m) { return (a * b) % m; }
static uint64_t addmod(uint64_t a, uint64_t b, uint64_t m) { uint64_t s = a + b; return s >= m ? s - m : s; }
static uint64_t step(uint64_t x, uint64_t m) { return addmod(mulmod(x, x, m), 1, m); }
int main(int argc, char **argv) {
    (void)argv;
    uint64_t x = 2 + (uint64_t)argc, m = 1000000007ULL, acc = 0;
    long n = 30000000 + argc - 1;
    for (long i = 0; i < n; i++) { x = step(x, m); acc ^= x + (uint64_t)i; }
    printf("%llu\n", (unsigned long long)acc);
    return 0;
}
