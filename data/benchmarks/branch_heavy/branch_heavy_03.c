#include <stdio.h>
int main(int argc, char **argv) {
    (void)argv;
    long lim = 150000 + argc - 1; unsigned long long steps = 0;
    for (long i = 1; i <= lim; i++) { unsigned long long x = (unsigned long long)i; while (x != 1) { x = (x & 1) ? 3 * x + 1 : x >> 1; steps++; } }
    printf("%llu\n", steps);
    return 0;
}
