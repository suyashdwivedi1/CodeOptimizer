#include <stdio.h>
int main(int argc, char **argv) {
    (void)argv;
    long s = 0; int n = 500 + argc - 1;
    for (int i = 0; i < n; i++) s += (i * 5) % 7;
    printf("%ld\n", s);
    return 0;
}
