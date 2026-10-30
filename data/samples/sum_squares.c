// Integer loop with a repeated computation and dead code
#include <stdio.h>
static int sq(int x) { return x * x; }
int main(int argc, char **argv) {
    (void)argv;
    long s = 0; int unused = 0;
    for (int r = 0; r < 20000; r++)
        for (int i = 0; i < 1000; i++) { s += sq(i + argc) % 7 + sq(i + argc) % 5; unused += i; }
    printf("%ld\n", s);
    return 0;
}
