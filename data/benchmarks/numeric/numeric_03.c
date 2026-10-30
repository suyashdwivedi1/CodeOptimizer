#include <stdio.h>
int main(int argc, char **argv) {
    (void)argv;
    long n = 25000000 + argc - 1;
    unsigned s = 17u + (unsigned)argc; long in = 0;
    for (long i = 0; i < n; i++) { s = s * 1103515245u + 12345u; double x = (double)(s >> 8) / 16777216.0; s = s * 1103515245u + 12345u; double y = (double)(s >> 8) / 16777216.0; if (x * x + y * y <= 1.0) in++; }
    printf("%ld\n", in);
    return 0;
}
