#include <stdio.h>
int main(int argc, char **argv) {
    (void)argv;
    long n = 6000000 + argc - 1;
    double tot = 0.0;
    for (long i = 1; i <= n / 20; i++) { double v = (double)i, g = v / 2.0; for (int k = 0; k < 20; k++) g = 0.5 * (g + v / g); tot += g; }
    printf("%.6f\n", tot);
    return 0;
}
