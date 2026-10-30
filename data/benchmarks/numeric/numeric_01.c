#include <stdio.h>
int main(int argc, char **argv) {
    (void)argv;
    long n = 15000000 + argc - 1;
    double h = 1.0 / (double)n, s = 0.0;
    for (long i = 0; i < n; i++) { double x = (double)i * h; s += (x * x * x - 2.0 * x + 1.0) * h; }
    printf("%.6f\n", s);
    return 0;
}
