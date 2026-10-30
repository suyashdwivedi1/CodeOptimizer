#include <stdio.h>
int main(int argc, char **argv) {
    (void)argv;
    long lim = 20000000 + argc - 1; unsigned long long steps = 0;
    for (long i = 0; i < lim; i++) { long m = i % 15; if (m == 0) steps += 15; else if (m % 5 == 0) steps += 5; else if (m % 3 == 0) steps += 3; else if ((i ^ (i >> 3)) & 1) steps += 2; else steps += 1; }
    printf("%llu\n", steps);
    return 0;
}
