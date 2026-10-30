#include <stdio.h>
#include <stdint.h>
int main(int argc, char **argv) {
    (void)argv;
    uint64_t x = 88172645463325252ULL + (uint64_t)argc, acc = 0;
    long n = 40000000 + argc - 1;
    for (long i = 0; i < n; i++) {
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        acc += (x % 65521) * (uint64_t)(i & 3) + (x >> 3);
    }
    printf("%llu\n", (unsigned long long)acc);
    return 0;
}
